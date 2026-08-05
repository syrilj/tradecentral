"""Regime-aware live multi-stream signal blend.

This is the honest version of a "self-adapting model":

* Streams (technical, sector, sentiment, fundamental) are scored from the
  *latest available* market/context data — so the composite updates as inputs
  change.
* Base stream weights are pre-registered per volatility×trend regime.
* Soft online reweighting may tilt those weights using recent stream hit-rates
  or ICs, with floors so one lucky window cannot monopolize the blend.
* The output is an **ordinal adaptive blend**, never a calibrated probability,
  never a promotion or live-capital authorization.

Lumibot-style broker loops and continuous model retrain are intentionally out
of scope.  Frozen promoted models still own execution eligibility; this module
only ranks attention and surfaces regime-conditioned agreement.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from edge.research.regimes import classify_regimes


SCHEMA_VERSION = "adaptive-live-signal-v1"
SCORE_KIND = "ordinal_adaptive_blend"
STREAM_NAMES = ("technical", "sector", "sentiment", "fundamental")

# Pre-registered base weights by (volatility_regime, trend_regime).
# High-vol regimes lean on sentiment / risk structure; trend regimes lean on
# technical + sector continuity.  Every map sums to 1.0.
_REGIME_WEIGHTS: dict[tuple[str, str], dict[str, float]] = {
    ("LOW", "UP"): {"technical": 0.40, "sector": 0.25, "sentiment": 0.15, "fundamental": 0.20},
    ("LOW", "FLAT"): {"technical": 0.30, "sector": 0.25, "sentiment": 0.20, "fundamental": 0.25},
    ("LOW", "DOWN"): {"technical": 0.30, "sector": 0.20, "sentiment": 0.25, "fundamental": 0.25},
    ("MEDIUM", "UP"): {"technical": 0.35, "sector": 0.25, "sentiment": 0.20, "fundamental": 0.20},
    ("MEDIUM", "FLAT"): {"technical": 0.28, "sector": 0.27, "sentiment": 0.22, "fundamental": 0.23},
    ("MEDIUM", "DOWN"): {"technical": 0.28, "sector": 0.22, "sentiment": 0.28, "fundamental": 0.22},
    ("HIGH", "UP"): {"technical": 0.28, "sector": 0.22, "sentiment": 0.30, "fundamental": 0.20},
    ("HIGH", "FLAT"): {"technical": 0.22, "sector": 0.23, "sentiment": 0.35, "fundamental": 0.20},
    ("HIGH", "DOWN"): {"technical": 0.22, "sector": 0.18, "sentiment": 0.38, "fundamental": 0.22},
}
_DEFAULT_WEIGHTS = {"technical": 0.30, "sector": 0.25, "sentiment": 0.22, "fundamental": 0.23}
_ONLINE_FLOOR = 0.08  # no adapted weight below this if the stream is present
_NEUTRAL_BAND = 0.12


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().removesuffix(".US")


def _normalize_frame(raw: Any) -> pd.DataFrame:
    if not hasattr(raw, "copy") or not hasattr(raw, "columns"):
        return pd.DataFrame()
    frame = raw.copy()
    frame = frame.rename(columns={str(c): str(c).lower() for c in frame.columns})
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame.sort_index()
    frame.loc[:, list(required)] = frame.loc[:, list(required)].apply(
        pd.to_numeric, errors="coerce",
    )
    return frame.dropna(subset=["open", "close"])


def _zscore_last(series: pd.Series, lookback: int = 60) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < max(10, lookback // 3):
        return None
    window = clean.iloc[-lookback:] if len(clean) >= lookback else clean
    if len(window) < 8:
        return None
    mu = float(window.iloc[:-1].mean()) if len(window) > 8 else float(window.mean())
    sd = float(window.iloc[:-1].std(ddof=1)) if len(window) > 8 else float(window.std(ddof=1))
    if not math.isfinite(sd) or sd <= 1e-12:
        return 0.0
    return (float(window.iloc[-1]) - mu) / sd


def bars_per_session(index: pd.Index) -> float:
    """Estimate bars per ~6.5h equity session from median spacing (1 for daily)."""
    if len(index) < 3:
        return 1.0
    try:
        ts = pd.to_datetime(pd.Index(index), errors="coerce")
        deltas = ts.to_series().diff().dt.total_seconds().dropna()
    except Exception:
        return 1.0
    if deltas.empty:
        return 1.0
    med = float(deltas.median())
    if not math.isfinite(med) or med <= 0:
        return 1.0
    # Daily bars ≈ 86400s; hourly ≈ 3600s → ~6.5 bars/session.
    if med >= 20 * 3600:
        return 1.0
    return max(1.0, min(48.0, (6.5 * 3600.0) / med))


def detect_bar_freq(index: pd.Index) -> str:
    bps = bars_per_session(index)
    if bps >= 4.0:
        return "1h"
    if bps >= 1.5:
        return "intraday"
    return "1d"


def calendar_return(close: pd.Series, *, days: float) -> float | None:
    """Return over approximately ``days`` calendar days using the bar index."""
    if close is None or len(close) < 3 or days <= 0:
        return None
    try:
        idx = pd.to_datetime(close.index, errors="coerce")
    except Exception:
        return None
    if idx.isna().all():
        return None
    last_ts = idx[-1]
    if pd.isna(last_ts):
        return None
    target = last_ts - pd.Timedelta(days=float(days))
    # Last bar at or before target.
    positions = idx.get_indexer([target], method="ffill")
    pos = int(positions[0]) if len(positions) else -1
    if pos < 0 or pos >= len(close) - 1:
        # Fallback: bar-count approximation.
        bps = bars_per_session(close.index)
        n = max(1, int(round(days * bps)))
        if len(close) <= n:
            return None
        base = float(close.iloc[-1 - n])
    else:
        base = float(close.iloc[pos])
    last = float(close.iloc[-1])
    if not math.isfinite(base) or not math.isfinite(last) or base <= 0 or last <= 0:
        return None
    return last / base - 1.0


def rolling_mean_over_days(close: pd.Series, *, days: float) -> float | None:
    if close is None or len(close) < 5 or days <= 0:
        return None
    bps = bars_per_session(close.index)
    n = max(2, int(round(days * bps)))
    if len(close) < n:
        return None
    window = close.iloc[-n:]
    value = float(window.mean())
    return value if math.isfinite(value) else None


def infer_bar_meta(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or len(frame) == 0:
        return {"bar_freq": "unknown", "bars_per_session": 1.0, "n_bars": 0}
    bps = bars_per_session(frame.index)
    return {
        "bar_freq": detect_bar_freq(frame.index),
        "bars_per_session": round(bps, 2),
        "n_bars": int(len(frame)),
    }


def score_technical(frame: pd.DataFrame) -> dict[str, Any]:
    """Momentum + trend structure on completed bars (daily or intraday)."""
    meta = infer_bar_meta(frame)
    min_bars = 30 if meta["bar_freq"] == "1d" else 80
    if len(frame) < min_bars:
        return {
            "score": None,
            "quality": "missing",
            "components": {},
            "reasons": ["insufficient_bars"],
            "bar_freq": meta["bar_freq"],
        }
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    ret_5 = calendar_return(close, days=5)
    ret_20 = calendar_return(close, days=20)
    ma20 = rolling_mean_over_days(close, days=20)
    ma60 = rolling_mean_over_days(close, days=60)
    last = float(close.iloc[-1])
    trend = None
    if ma20 is not None and ma60 is not None and ma60 > 0:
        trend = (ma20 / ma60 - 1.0) * 8.0
    lookback_vol = max(20, int(round(20 * float(meta["bars_per_session"]))))
    vol_z = _zscore_last(volume, lookback=lookback_vol)
    mom = 0.0
    n = 0
    components: dict[str, float | None] = {
        "ret_5d": ret_5,
        "ret_20d": ret_20,
        "trend_ma20_ma60": None if trend is None else trend / 8.0,
        "volume_z": vol_z,
    }
    if ret_5 is not None:
        mom += _clip(ret_5 / 0.08)
        n += 1
    if ret_20 is not None:
        mom += _clip(ret_20 / 0.15)
        n += 1
    if trend is not None:
        mom += _clip(trend)
        n += 1
    if n == 0:
        return {
            "score": None,
            "quality": "missing",
            "components": components,
            "reasons": ["no_technical_components"],
            "bar_freq": meta["bar_freq"],
        }
    score = mom / n
    # Elevated volume amplifies conviction; it never invents a side alone.
    if vol_z is not None and abs(vol_z) >= 1.0 and score != 0:
        score = score * (1.0 + min(abs(vol_z), 2.5) * 0.08)
    score = _clip(score)
    reasons = []
    if ret_5 is not None and abs(ret_5) >= 0.03:
        reasons.append("strong_5d_move")
    if ma20 is not None and last > ma20:
        reasons.append("above_ma20")
    elif ma20 is not None and last < ma20:
        reasons.append("below_ma20")
    if meta["bar_freq"] != "1d":
        reasons.append(f"intraday_{meta['bar_freq']}")
    return {
        "score": round(score, 4),
        "quality": "ok",
        "components": {k: (None if v is None else round(float(v), 5)) for k, v in components.items()},
        "reasons": reasons,
        "last": round(last, 4),
        "bar_freq": meta["bar_freq"],
        "bars_per_session": meta["bars_per_session"],
    }


def score_sector(
    *,
    technical_score: float | None,
    sector_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Align symbol impulse with sector ETF / money-flow context when present."""
    ctx = dict(sector_context or {})
    flow_dir = str(ctx.get("flow_direction") or ctx.get("direction") or "").strip().lower()
    rs_1d = _finite(ctx.get("rs_1d"))
    rs_5d = _finite(ctx.get("rs_5d"))
    flow_score = _finite(ctx.get("flow_score") or ctx.get("definitive_score"))
    if not any(v is not None for v in (rs_1d, rs_5d, flow_score)) and flow_dir not in {"in", "out", "long", "short", "up", "down"}:
        return {
            "score": None,
            "quality": "missing",
            "components": {},
            "reasons": ["no_sector_context"],
            "sector_etf": ctx.get("sector_etf") or ctx.get("etf"),
            "sector_name": ctx.get("sector_name") or ctx.get("name"),
        }
    signed = 0.0
    n = 0
    if rs_5d is not None:
        signed += _clip(rs_5d / 0.04)
        n += 1
    if rs_1d is not None:
        signed += _clip(rs_1d / 0.015)
        n += 1
    if flow_score is not None:
        signed += _clip(flow_score / 0.05 if abs(flow_score) < 2 else flow_score)
        n += 1
    if flow_dir in {"in", "long", "up", "money_in"}:
        signed += 0.35
        n += 1
    elif flow_dir in {"out", "short", "down", "money_out"}:
        signed -= 0.35
        n += 1
    score = _clip(signed / max(n, 1))
    # Mild agreement boost with technical direction when both present.
    if technical_score is not None and score * technical_score > 0:
        score = _clip(score * 1.08)
    reasons = []
    if flow_dir:
        reasons.append(f"sector_flow_{flow_dir}")
    if rs_5d is not None and abs(rs_5d) >= 0.02:
        reasons.append("sector_rs_elevated")
    return {
        "score": round(score, 4),
        "quality": "ok",
        "components": {
            "rs_1d": None if rs_1d is None else round(rs_1d, 5),
            "rs_5d": None if rs_5d is None else round(rs_5d, 5),
            "flow_score": None if flow_score is None else round(flow_score, 5),
            "flow_direction": flow_dir or None,
        },
        "reasons": reasons,
        "sector_etf": ctx.get("sector_etf") or ctx.get("etf"),
        "sector_name": ctx.get("sector_name") or ctx.get("name"),
    }


def score_sentiment(market_sentiment: Mapping[str, Any] | None) -> dict[str, Any]:
    """Desk-level risk sentiment (vol complex / COT / short vol) as a stream.

    Higher score = risk-on tilt.  Missing blocks degrade quality rather than
    inventing a neutral market.
    """
    raw = dict(market_sentiment or {})
    if not raw:
        return {"score": None, "quality": "missing", "components": {}, "reasons": ["no_market_sentiment"]}

    components: dict[str, float | None] = {}
    parts: list[float] = []
    reasons: list[str] = []

    # Prefer an explicit composite if a producer already built one.
    for key in ("risk_on_score", "composite_score", "sentiment_score"):
        value = _finite(raw.get(key))
        if value is not None:
            score = _clip(value if abs(value) <= 1.5 else value / 100.0)
            return {
                "score": round(score, 4),
                "quality": str(raw.get("quality") or "ok"),
                "components": {key: round(score, 4)},
                "reasons": ["explicit_composite"],
                "asof": raw.get("asof"),
            }

    vol = raw.get("vol") if isinstance(raw.get("vol"), Mapping) else raw.get("vol_complex")
    if isinstance(vol, Mapping):
        vix = _finite(vol.get("VIX") or vol.get("vix"))
        tail = _finite(vol.get("tail_risk") or vol.get("tail"))
        slope = _finite(vol.get("term_slope") or vol.get("slope"))
        components["vix"] = vix
        components["tail_risk"] = tail
        components["term_slope"] = slope
        if vix is not None:
            # Map VIX ~12 → +0.6, ~20 → 0, ~32 → -0.7
            parts.append(_clip((20.0 - vix) / 12.0))
            if vix >= 25:
                reasons.append("elevated_vix")
        if tail is not None:
            parts.append(_clip(1.0 - tail / 1.5))
            if tail >= 1.5:
                reasons.append("elevated_tail_risk")
        if slope is not None:
            # Contango (positive slope) is usually risk-on-ish for equity desks.
            parts.append(_clip(slope / 0.5))

    short_vol = raw.get("short_volume") if isinstance(raw.get("short_volume"), Mapping) else None
    if isinstance(short_vol, Mapping):
        short_z = _finite(short_vol.get("zscore") or short_vol.get("short_ratio_z"))
        components["short_ratio_z"] = short_z
        if short_z is not None:
            # Elevated shorting vs history = risk-off / bearish pressure.
            parts.append(_clip(-short_z / 2.0))
            if abs(short_z) >= 2.0:
                reasons.append("short_volume_extreme")

    cot = raw.get("cot") if isinstance(raw.get("cot"), Mapping) else None
    if isinstance(cot, Mapping):
        cot_score = _finite(cot.get("risk_on_score") or cot.get("spec_net_z"))
        components["cot"] = cot_score
        if cot_score is not None:
            parts.append(_clip(cot_score if abs(cot_score) <= 1.5 else cot_score / 3.0))

    if not parts:
        return {
            "score": None,
            "quality": "missing",
            "components": components,
            "reasons": ["sentiment_blocks_incomplete"],
            "asof": raw.get("asof"),
        }
    score = _clip(float(np.mean(parts)))
    return {
        "score": round(score, 4),
        "quality": "ok",
        "components": {k: (None if v is None else round(float(v), 4)) for k, v in components.items()},
        "reasons": reasons,
        "asof": raw.get("asof"),
    }


def score_fundamental(
    frame: pd.DataFrame,
    *,
    fundamental_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Slow-moving proxies: realized quality of trend + optional PEAD/short context.

    True accounting fundamentals are not always local.  We combine:
    * multi-horizon return consistency (quality of trend),
    * optional PEAD / catalyst ordinal scores when supplied,
    * optional FINRA short-ratio extremes for the symbol.
    """
    ctx = dict(fundamental_context or {})
    parts: list[float] = []
    components: dict[str, float | None] = {}
    reasons: list[str] = []
    meta = infer_bar_meta(frame)

    if len(frame) >= 40:
        close = frame["close"].astype(float)
        ret_20 = calendar_return(close, days=20)
        ret_60 = calendar_return(close, days=60)
        components["ret_20d"] = ret_20
        components["ret_60d"] = ret_60
        if ret_20 is not None and ret_60 is not None:
            # Consistent direction across horizons scores higher than a single spike.
            agree = 1.0 if ret_20 * ret_60 > 0 else -0.4 if ret_20 * ret_60 < 0 else 0.0
            magnitude = _clip((ret_20 / 0.12 + ret_60 / 0.25) / 2.0)
            parts.append(_clip(0.65 * magnitude + 0.35 * agree * abs(magnitude)))
            if agree > 0:
                reasons.append("multi_horizon_agreement")
            elif agree < 0:
                reasons.append("multi_horizon_conflict")

    pead = _finite(ctx.get("pead_score") or ctx.get("catalyst_score") or ctx.get("ordinal_score"))
    if pead is not None:
        components["pead_or_catalyst"] = pead
        parts.append(_clip(pead if abs(pead) <= 1.5 else pead / 100.0))
        reasons.append("catalyst_context")

    short_z = _finite(ctx.get("short_ratio_z") or ctx.get("finra_short_z"))
    if short_z is not None:
        components["short_ratio_z"] = short_z
        parts.append(_clip(-short_z / 2.5))
        if abs(short_z) >= 2.0:
            reasons.append("symbol_short_extreme")

    if not parts:
        return {
            "score": None,
            "quality": "missing",
            "components": components,
            "reasons": ["no_fundamental_proxy"],
            "bar_freq": meta["bar_freq"],
        }
    return {
        "score": round(_clip(float(np.mean(parts))), 4),
        "quality": "ok",
        "components": {k: (None if v is None else round(float(v), 5)) for k, v in components.items()},
        "reasons": reasons,
        "bar_freq": meta["bar_freq"],
    }


def detect_live_regime(frame: pd.DataFrame) -> dict[str, Any]:
    """Causal regime labels from the same classify_regimes helper used in research.

    Window lengths scale with bars-per-session so hourly data still maps to
    ~20-day vol / ~60-day trend rather than 20/60 hours.
    """
    meta = infer_bar_meta(frame)
    bps = float(meta["bars_per_session"] or 1.0)
    vol_window = max(20, int(round(20 * bps)))
    trend_window = max(60, int(round(60 * bps)))
    min_bars = trend_window + 5
    if len(frame) < min_bars:
        return {
            "volatility_regime": None,
            "trend_regime": None,
            "bear_market": None,
            "quality": "missing",
            "reasons": ["insufficient_bars_for_regime"],
            "bar_freq": meta["bar_freq"],
            "volatility_window": vol_window,
            "trend_window": trend_window,
        }
    close = frame["close"].astype(float)
    labels = classify_regimes(
        close,
        volatility_window=vol_window,
        trend_window=trend_window,
    )
    last = labels.iloc[-1]
    vol = last.get("volatility_regime")
    trend = last.get("trend_regime")
    bear = last.get("bear_market")
    return {
        "volatility_regime": None if pd.isna(vol) else str(vol),
        "trend_regime": None if pd.isna(trend) else str(trend),
        "bear_market": None if pd.isna(bear) else bool(bear),
        "realized_volatility": _finite(last.get("realized_volatility")),
        "drawdown": _finite(last.get("drawdown")),
        "quality": "ok" if not pd.isna(vol) and not pd.isna(trend) else "degraded",
        "reasons": [],
        "bar_freq": meta["bar_freq"],
        "volatility_window": vol_window,
        "trend_window": trend_window,
    }


def base_weights_for_regime(regime: Mapping[str, Any]) -> dict[str, float]:
    vol = str(regime.get("volatility_regime") or "")
    trend = str(regime.get("trend_regime") or "")
    weights = dict(_REGIME_WEIGHTS.get((vol, trend), _DEFAULT_WEIGHTS))
    # In declared bear markets, shift slightly toward sentiment + fundamental defense.
    if regime.get("bear_market") is True:
        weights["sentiment"] = weights.get("sentiment", 0.2) + 0.06
        weights["fundamental"] = weights.get("fundamental", 0.2) + 0.04
        weights["technical"] = max(0.12, weights.get("technical", 0.3) - 0.06)
        weights["sector"] = max(0.12, weights.get("sector", 0.25) - 0.04)
    total = sum(weights.values()) or 1.0
    return {name: weights.get(name, 0.0) / total for name in STREAM_NAMES}


def adapt_weights(
    base: Mapping[str, float],
    *,
    stream_performance: Mapping[str, float] | None = None,
    present_streams: Iterable[str],
) -> tuple[dict[str, float], str]:
    """Soft online reweight from recent stream performance in [-1, 1] or [0, 1].

    Performance may be rolling hit-rate (0..1) or signed IC (-1..1).  Missing
    streams are zeroed; present streams keep at least ``_ONLINE_FLOOR`` mass
    after renormalization when any performance signal is supplied.
    """
    present = {str(name) for name in present_streams if name in STREAM_NAMES}
    if not present:
        return {name: 0.0 for name in STREAM_NAMES}, "no_present_streams"

    base_w = {name: float(base.get(name, 0.0)) for name in STREAM_NAMES}
    # Drop missing streams and renorm base over present only.
    masked = {name: (base_w[name] if name in present else 0.0) for name in STREAM_NAMES}
    base_sum = sum(masked.values()) or 1.0
    masked = {name: masked[name] / base_sum for name in STREAM_NAMES}

    perf = dict(stream_performance or {})
    if not perf:
        return masked, "regime_map_only"

    scaled: dict[str, float] = {}
    for name in STREAM_NAMES:
        if name not in present:
            scaled[name] = 0.0
            continue
        raw = _finite(perf.get(name))
        if raw is None:
            multiplier = 1.0
        elif 0.0 <= raw <= 1.0:
            # Hit-rate style: 0.5 neutral, >0.5 boost.
            multiplier = 0.55 + raw
        else:
            # Signed IC style.
            multiplier = 1.0 + 0.75 * _clip(raw)
        scaled[name] = max(_ONLINE_FLOOR, masked[name] * max(multiplier, 0.15))

    total = sum(scaled.values()) or 1.0
    adapted = {name: scaled[name] / total for name in STREAM_NAMES}
    return adapted, "regime_map_plus_online_soft"


def _agreement_band(scores: Mapping[str, float | None]) -> str:
    present = [float(v) for v in scores.values() if v is not None]
    if len(present) < 2:
        return "thin"
    signs = [1 if v > _NEUTRAL_BAND else -1 if v < -_NEUTRAL_BAND else 0 for v in present]
    nonzero = [s for s in signs if s != 0]
    if len(nonzero) < 2:
        return "thin"
    if all(s == nonzero[0] for s in nonzero) and len(nonzero) >= 3:
        return "strong"
    if all(s == nonzero[0] for s in nonzero):
        return "moderate"
    return "conflicted"


def blend_streams(
    stream_scores: Mapping[str, float | None],
    weights: Mapping[str, float],
) -> tuple[float | None, dict[str, float]]:
    contrib: dict[str, float] = {}
    num = 0.0
    den = 0.0
    for name in STREAM_NAMES:
        score = stream_scores.get(name)
        weight = float(weights.get(name, 0.0))
        if score is None or weight <= 0:
            contrib[name] = 0.0
            continue
        piece = weight * float(score)
        contrib[name] = round(piece, 5)
        num += piece
        den += weight
    if den <= 1e-12:
        return None, contrib
    # Renormalize so missing streams do not silently shrink the signal toward 0
    # without the operator seeing it — weight mass is redistributed among present.
    return _clip(num / den), contrib


@dataclass(frozen=True)
class AdaptiveSignalInputs:
    symbol: str
    bars: Any
    sector_context: Mapping[str, Any] | None = None
    market_sentiment: Mapping[str, Any] | None = None
    fundamental_context: Mapping[str, Any] | None = None
    stream_performance: Mapping[str, float] | None = None


def score_symbol(inputs: AdaptiveSignalInputs) -> dict[str, Any]:
    """Score one symbol into an adaptive multi-stream blend."""
    symbol = _symbol(inputs.symbol)
    frame = _normalize_frame(inputs.bars)
    asof = None
    if len(frame):
        asof = pd.Timestamp(frame.index[-1]).isoformat()

    regime = detect_live_regime(frame)
    technical = score_technical(frame)
    tech_score = _finite(technical.get("score"))
    sector = score_sector(technical_score=tech_score, sector_context=inputs.sector_context)
    sentiment = score_sentiment(inputs.market_sentiment)
    fundamental = score_fundamental(frame, fundamental_context=inputs.fundamental_context)

    streams = {
        "technical": technical,
        "sector": sector,
        "sentiment": sentiment,
        "fundamental": fundamental,
    }
    stream_scores = {name: _finite(streams[name].get("score")) for name in STREAM_NAMES}
    present = [name for name, score in stream_scores.items() if score is not None]

    base = base_weights_for_regime(regime)
    adapted, adaptation_mode = adapt_weights(
        base,
        stream_performance=inputs.stream_performance,
        present_streams=present,
    )
    composite, contributions = blend_streams(stream_scores, adapted)

    if composite is None:
        side = "neutral"
        state = "ABSTAIN"
    elif composite >= _NEUTRAL_BAND:
        side = "long"
        state = "WATCH"
    elif composite <= -_NEUTRAL_BAND:
        side = "short"
        state = "WATCH"
    else:
        side = "neutral"
        state = "WATCH"

    band = _agreement_band(stream_scores)
    reasons: list[str] = []
    for name in STREAM_NAMES:
        reasons.extend(f"{name}:{r}" for r in (streams[name].get("reasons") or [])[:3])
    if band == "conflicted":
        reasons.append("stream_conflict")
    if regime.get("quality") != "ok":
        reasons.append("regime_degraded")

    bar_meta = infer_bar_meta(frame)
    return {
        "schema_version": SCHEMA_VERSION,
        "score_kind": SCORE_KIND,
        "decision_authorized": False,
        "live_capital_authorized": False,
        "promotion_authorized": False,
        "symbol": symbol,
        "asof": asof,
        "state": state,
        "side": side,
        "composite_score": None if composite is None else round(float(composite), 4),
        "agreement_band": band,
        "regime": regime,
        "bar_freq": bar_meta["bar_freq"],
        "bars_per_session": bar_meta["bars_per_session"],
        "n_bars": bar_meta["n_bars"],
        "streams": streams,
        "stream_scores": stream_scores,
        "stream_performance_used": {
            name: _finite((inputs.stream_performance or {}).get(name))
            for name in STREAM_NAMES
            if inputs.stream_performance and name in inputs.stream_performance
        },
        "weights": {
            "base": {k: round(v, 4) for k, v in base.items()},
            "adapted": {k: round(v, 4) for k, v in adapted.items()},
            "adaptation_mode": adaptation_mode,
            "contributions": contributions,
        },
        "present_streams": present,
        "reasons": reasons[:16],
        "caveat": (
            "Ordinal adaptive blend from live-available streams. "
            "Weights shift with regime and optional recent stream performance. "
            "Not a calibrated probability, not a trade authorization, not a broker order."
        ),
    }


def scan_adaptive_signals(
    *,
    symbols: Sequence[str],
    candle_loader: Callable[[str], Any],
    sector_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    market_sentiment: Mapping[str, Any] | None = None,
    fundamental_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    stream_performance: Mapping[str, float] | None = None,
    row_limit: int = 40,
) -> dict[str, Any]:
    """Rank a universe by |composite_score| for desk attention."""
    sector_map = dict(sector_by_symbol or {})
    fund_map = dict(fundamental_by_symbol or {})
    rows: list[dict[str, Any]] = []
    failures = 0
    requested = list(dict.fromkeys(_symbol(s) for s in symbols if _symbol(s)))

    for symbol in requested:
        try:
            payload = score_symbol(
                AdaptiveSignalInputs(
                    symbol=symbol,
                    bars=candle_loader(symbol),
                    sector_context=sector_map.get(symbol),
                    market_sentiment=market_sentiment,
                    fundamental_context=fund_map.get(symbol),
                    stream_performance=stream_performance,
                )
            )
        except Exception:
            failures += 1
            continue
        if payload.get("composite_score") is None and not payload.get("present_streams"):
            failures += 1
            continue
        rows.append(payload)

    rows.sort(
        key=lambda row: (
            -abs(float(row.get("composite_score") or 0.0)),
            str(row.get("symbol") or ""),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["attention_rank"] = rank

    asof = max((str(row.get("asof") or "") for row in rows), default=None)
    regime_counts: dict[str, int] = {}
    for row in rows:
        reg = row.get("regime") or {}
        key = f"{reg.get('volatility_regime') or '?'}/{reg.get('trend_regime') or '?'}"
        regime_counts[key] = regime_counts.get(key, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "score_kind": SCORE_KIND,
        "decision_authorized": False,
        "live_capital_authorized": False,
        "quality": "ok" if rows else "missing",
        "asof": asof,
        "rows": rows[: max(1, int(row_limit))],
        "coverage": {
            "requested": len(requested),
            "scored": len(rows),
            "failed": failures,
        },
        "regime_histogram": regime_counts,
        "stream_performance": dict(stream_performance or {}),
        "caveat": (
            "Live multi-stream adaptive ranking for attention only. "
            "Does not place orders, authorize capital, or replace promoted model gates."
        ),
    }


def market_sentiment_from_dashboard_blocks(
    *,
    vol: Mapping[str, Any] | None = None,
    sentiment_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collapse dashboard/status blocks into the sentiment stream input shape."""
    payload: dict[str, Any] = {}
    if vol:
        payload["vol"] = dict(vol)
        payload["asof"] = vol.get("date") or vol.get("asof")
    sent = dict(sentiment_payload or {})
    if sent:
        # sentiment_anomalies payload structure is blocky; pass through useful keys.
        if "vol" in sent and "vol" not in payload:
            payload["vol"] = sent.get("vol")
        if "short_volume" in sent:
            payload["short_volume"] = sent.get("short_volume")
        if "cot" in sent:
            payload["cot"] = sent.get("cot")
        if sent.get("asof"):
            payload["asof"] = sent.get("asof")
        # Optional pre-aggregated fields if present.
        for key in ("risk_on_score", "composite_score", "sentiment_score", "quality"):
            if key in sent:
                payload[key] = sent[key]
    return payload
