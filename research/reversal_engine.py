"""Live reversal read for one symbol, and a universe scan.

Computes the same causal feature frame the study was run on
(``research.reversal_signals`` + ``research.reversal_study.directional_frame``)
and reads the latest bar against what the study *measured out of sample*
(``runs/reversal_study/<tf>/summary.json``).

Honesty rules this module keeps:
* Every signal and trigger is shown with the test-period number it earned,
  never a hand-picked confidence.
* The model probability is only emitted when that side's model passed its
  out-of-sample gate (AUC CI above 0.52, calibrated within 6 points).
  Otherwise ``probability`` is ``None`` and ``probability_reason`` says why.
* Context the study used but the live read can't get (breadth on a bar the
  local universe hasn't reached) is left missing and listed, not guessed.
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from edge.research import reversal_signals as rs
from edge.research import reversal_study as study

ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = ROOT / "runs" / "reversal_study"
CHART_BARS = {"1h": 140, "1d": 130}

_ART_LOCK = threading.Lock()
_ART_CACHE: dict[str, tuple[float, dict | None, dict | None]] = {}
_BREADTH_LOCK = threading.Lock()
_BREADTH_CACHE: dict[str, tuple[float, pd.DataFrame | None]] = {}
_BREADTH_TTL_S = 1800.0


def load_artifacts(tf: str) -> tuple[dict | None, dict | None]:
    """(summary, models) for a timeframe, reloaded when the files change."""
    s_path = STUDY_DIR / tf / "summary.json"
    m_path = STUDY_DIR / tf / "model.joblib"
    if not s_path.is_file():
        return None, None
    mtime = s_path.stat().st_mtime
    with _ART_LOCK:
        hit = _ART_CACHE.get(tf)
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
    try:
        summary = json.loads(s_path.read_text())
    except Exception:
        summary = None
    models = None
    if m_path.is_file():
        try:
            import joblib

            models = joblib.load(m_path)
        except Exception:
            models = None
    with _ART_LOCK:
        _ART_CACHE[tf] = (mtime, summary, models)
    return summary, models


def _f(x: Any, nd: int = 4) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _clean(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.dropna(subset=["open", "high", "low", "close"])
    return bars[~bars.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------------------
# market context


def universe_breadth(tf: str, loader) -> pd.DataFrame | None:
    """Share of the local universe beyond +/-100 on the MACD-HA, per bar.
    ``loader(symbol)`` returns that symbol's bars. Cached for 30 minutes."""
    now = time.time()
    with _BREADTH_LOCK:
        hit = _BREADTH_CACHE.get(tf)
        if hit and now - hit[0] < _BREADTH_TTL_S:
            return hit[1]
    src = study.DATA_1H if tf == "1h" else study.DATA_1D
    frames = []
    for path in sorted(src.glob("*.parquet")):
        try:
            bars = _clean(pd.read_parquet(path, columns=list(rs.OHLCV)))
        except Exception:
            continue
        if len(bars) < 200:
            continue
        bars = bars.iloc[-400:]
        m = rs.st_macd_ha(bars)
        ok = m["macd_ha_c"].notna()
        frames.append(
            pd.DataFrame(
                {"below": (m["macd_ha_l"] < -100).astype(np.int16), "above": (m["macd_ha_h"] > 100).astype(np.int16), "n": np.int16(1)},
                index=bars.index,
            ).loc[ok]
        )
    result = None
    if frames:
        tot = frames[0]
        for fr in frames[1:]:
            tot = tot.add(fr, fill_value=0)
        good = tot["n"] >= 50
        result = pd.DataFrame(
            {"breadth_below": np.where(good, tot["below"] / tot["n"], np.nan), "breadth_above": np.where(good, tot["above"] / tot["n"], np.nan)},
            index=tot.index,
        )
    with _BREADTH_LOCK:
        _BREADTH_CACHE[tf] = (now, result)
    return result


def feature_frame(bars: pd.DataFrame, htf: pd.DataFrame, market: pd.DataFrame, breadth: pd.DataFrame | None, tf: str) -> pd.DataFrame:
    cfg = study.CONFIGS[tf]
    params = rs.FeatureParams(profile_sessions=cfg.profile_sessions, profile_bins=cfg.profile_bins)
    f = rs.build_features(bars, params)
    f = f.join(rs.align_htf(bars.index, rs.htf_context(htf), cfg.htf_freq))
    ctx = study.market_features(_clean(market)).reindex(bars.index)
    if breadth is not None:
        ctx = ctx.join(breadth.reindex(bars.index))
    else:
        ctx["breadth_below"] = np.nan
        ctx["breadth_above"] = np.nan
    return f.join(ctx)


def _candidate_side(row: pd.Series, leg_atr: float) -> int:
    if row["swing_dir"] < 0 and row["off_high_atr"] <= -leg_atr:
        return 1
    if row["swing_dir"] > 0 and row["off_low_atr"] >= leg_atr:
        return -1
    return 0


def _edge_word(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "unmeasured"
    if lo > 0:
        return "helps"
    if hi < 0:
        return "hurts"
    return "no_edge"


def _signal_rows(d_row: pd.Series, side_summary: dict | None) -> list[dict]:
    measured = {s["key"]: s for s in (side_summary or {}).get("signals", [])}
    out = []
    for key, _, desc in study.BINARY_PAIRS:
        test = (measured.get(key) or {}).get("test") or {}
        val = d_row.get(key)
        out.append(
            {
                "key": key,
                "label": desc,
                "on": bool(val) if val is not None and not (isinstance(val, float) and math.isnan(val)) else False,
                "test_rate": _f(test.get("rate")),
                "test_n": test.get("n"),
                "test_lift": _f(test.get("lift")),
                "test_lift_lo": _f(test.get("lo")),
                "test_lift_hi": _f(test.get("hi")),
                "measured_edge": _edge_word(test.get("lo"), test.get("hi")) if key in measured else "unmeasured",
            }
        )
    return out


def _trigger_rows(f: pd.DataFrame, side: int, summary: dict | None, lookback: int) -> list[dict]:
    """Which structural triggers fired in the last ``lookback`` bars, with the
    trade-level result the study measured for each."""
    label = "bottom" if side > 0 else "top"
    measured = {r["trigger"]: r for r in ((summary or {}).get("trades") or {}).get(label, [])}
    tail = f.iloc[-lookback:]
    early = (f["bull_div" if side > 0 else "bear_div"] | f["macd_os" if side > 0 else "macd_ob"]).rolling(10, min_periods=1).max().astype(bool)
    flags = {
        "reclaim": tail["svwap_reclaim" if side > 0 else "svwap_reject"],
        "macd_signal": tail["macd_os" if side > 0 else "macd_ob"],
        "divergence": tail["bull_div" if side > 0 else "bear_div"],
        "value_reentry": tail["val_reentry" if side > 0 else "vah_reentry"],
        "reclaim_confirmed": tail["svwap_reclaim" if side > 0 else "svwap_reject"] & early.iloc[-lookback:],
    }
    out = []
    for trig, (_, _, desc) in study.TRIGGERS.items():
        if trig in ("baseline", "swing_flip"):
            continue
        fl = flags[trig].to_numpy(bool)
        last_idx = int(np.flatnonzero(fl)[-1]) if fl.any() else None
        m = (measured.get(trig) or {}).get("all") or {}
        late = (measured.get(trig) or {}).get("late") or {}
        vs = m.get("vs_baseline") or {}
        vs_late = late.get("vs_baseline") or {}
        out.append(
            {
                "trigger": trig,
                "label": desc,
                "fired": last_idx is not None,
                "bars_ago": (len(fl) - 1 - last_idx) if last_idx is not None else None,
                "n": m.get("n"),
                "avg_r": _f(m.get("avg_r"), 3),
                "win_rate": _f(m.get("win_rate"), 3),
                "risk_atr_median": _f(m.get("risk_atr_median"), 2),
                "edge_r": _f(vs.get("edge_r"), 3),
                "edge_r_lo": _f(vs.get("lo"), 3),
                "edge_r_hi": _f(vs.get("hi"), 3),
                "edge_r_late": _f(vs_late.get("edge_r"), 3),
                "measured_edge": _edge_word(vs.get("lo"), vs.get("hi")),
            }
        )
    return out


def _probability(model, d_row: pd.DataFrame, side_summary: dict | None) -> tuple[float | None, str | None]:
    if not side_summary:
        return None, "no study artifact for this timeframe"
    m = side_summary.get("model") or {}
    if not m.get("passes"):
        auc = m.get("test_auc") or {}
        return None, (
            f"model did not pass its out-of-sample gate (test AUC {auc.get('auc', float('nan')):.3f}, "
            f"95% CI {auc.get('lo', float('nan')):.3f}-{auc.get('hi', float('nan')):.3f}) -- no probability is shown"
        )
    if model is None:
        return None, "model file missing"
    return float(model.predict(d_row)[0]), None


def _model_rank(model, d_row: pd.DataFrame, side_summary: dict | None) -> dict | None:
    """Where this bar's raw model score ranks against the test-period score
    distribution, with the hit rate that tier earned out of sample.

    A rank does not need the model to be calibrated -- only to order bars
    well -- so it can be shown when the probability can't. A tier is only
    reported as an edge when its whole lift interval sits above zero."""
    m = (side_summary or {}).get("model") or {}
    tiers = m.get("tiers") or {}
    if model is None or not tiers:
        return None
    raw_model = getattr(model, "model", model)
    score = float(raw_model.predict(d_row)[0])
    # tightest tier whose threshold the score clears
    order = sorted(tiers.items(), key=lambda kv: kv[1].get("score_threshold", kv[1].get("p_threshold", 0.0)), reverse=True)
    hit = None
    for name, t in order:
        thr = t.get("score_threshold", t.get("p_threshold"))
        if thr is not None and score >= thr:
            hit = (name, t)
            break
    base = (side_summary.get("base_test") or {}).get("rate")
    out = {"score": _f(score, 5), "base_rate_test": _f(base), "test_auc": m.get("test_auc"), "tiers": {}}
    for name, t in tiers.items():
        out["tiers"][name] = {
            "rate": _f(t.get("rate")), "lift": _f(t.get("lift")), "lift_lo": _f(t.get("lo")), "lift_hi": _f(t.get("hi")), "n": t.get("n"),
            "edge": _edge_word(t.get("lo"), t.get("hi")),
        }
    if hit is None:
        out.update(tier=None, tier_rate=None, tier_lift_lo=None, tier_edge="below_top_tiers")
    else:
        name, t = hit
        out.update(tier=name, tier_rate=_f(t.get("rate")), tier_lift=_f(t.get("lift")), tier_lift_lo=_f(t.get("lo")), tier_lift_hi=_f(t.get("hi")), tier_edge=_edge_word(t.get("lo"), t.get("hi")))
    return out


def read_symbol(
    symbol: str,
    bars: pd.DataFrame,
    htf: pd.DataFrame,
    market: pd.DataFrame,
    tf: str,
    *,
    source: str,
    breadth: pd.DataFrame | None = None,
) -> dict:
    """Payload for the Reversal tab. ``htf`` is daily bars for ``tf='1h'``;
    ignored for ``'1d'`` (weekly is built from ``bars``)."""
    cfg = study.CONFIGS[tf]
    summary, models = load_artifacts(tf)
    bars = _clean(bars)
    htf = rs.weekly_bars(bars) if tf == "1d" else _clean(htf)
    if len(bars) < 200 or len(htf) < 60:
        return {"symbol": symbol, "tf": tf, "measurable": False, "reason": f"only {len(bars)} bars / {len(htf)} HTF bars; need 200 / 60", "source": source}

    f = feature_frame(bars, htf, market, breadth, tf)
    last = f.iloc[-1]
    cand = _candidate_side(last, cfg.leg_atr)
    missing = [c for c in ("breadth_below", "mkt_macd", "htf_macd", "poc", "svwap") if pd.isna(last.get(c))]

    reads: dict[str, dict] = {}
    for side, name in ((1, "bottom"), (-1, "top")):
        d = study.directional_frame(f.iloc[[-1]], side)
        ss = ((summary or {}).get("sides") or {}).get(name)
        prob, reason = _probability((models or {}).get(name), d, ss)
        signals = _signal_rows(d.iloc[0], ss)
        on = [s for s in signals if s["on"]]
        model_meta = (ss or {}).get("model") or {}
        reads[name] = {
            "candidate": cand == side,
            # rank is only meaningful on bars inside the candidate set the tiers were scored on
            "rank": _model_rank((models or {}).get(name), d, ss) if cand == side else None,
            "signals": signals,
            "signals_on": len(on),
            "signals_on_with_edge": sum(1 for s in on if s["measured_edge"] == "helps"),
            "triggers": _trigger_rows(f, side, summary, lookback=10),
            "probability": _f(prob, 4),
            "probability_reason": reason,
            "base_rate_test": _f(((ss or {}).get("base_test") or {}).get("rate")),
            "model_auc": model_meta.get("test_auc"),
            "model_chosen": model_meta.get("chosen"),
            "model_tiers": model_meta.get("tiers"),
            "drivers": model_meta.get("drivers"),
            "lag": (ss or {}).get("lag"),
        }

    n = CHART_BARS[tf]
    tail = f.iloc[-n:]
    tb = bars.loc[tail.index]
    macd = rs.st_macd_ha(bars).loc[tail.index]
    sw = rs.swing_anchored_vwap(bars).loc[tail.index]
    chart = [
        {
            "t": ts.isoformat(),
            "o": _f(tb.at[ts, "open"]), "h": _f(tb.at[ts, "high"]), "l": _f(tb.at[ts, "low"]), "c": _f(tb.at[ts, "close"]),
            "v": _f(tb.at[ts, "volume"], 0), "rvol": _f(tail.at[ts, "rvol"], 3),
            "svwap": _f(tail.at[ts, "svwap"]), "dir": int(tail.at[ts, "swing_dir"]), "flip": bool(sw.at[ts, "swing_flip"]),
            "poc": _f(tail.at[ts, "poc"]), "val": _f(tail.at[ts, "val"]), "vah": _f(tail.at[ts, "vah"]),
            "m_o": _f(macd.at[ts, "macd_ha_o"], 2), "m_h": _f(macd.at[ts, "macd_ha_h"], 2),
            "m_l": _f(macd.at[ts, "macd_ha_l"], 2), "m_c": _f(macd.at[ts, "macd_ha_c"], 2),
            "m_sig": _f(macd.at[ts, "macd_signal"], 2),
            "os": bool(macd.at[ts, "macd_os"]), "ob": bool(macd.at[ts, "macd_ob"]),
            "reclaim": bool(tail.at[ts, "svwap_reclaim"]), "reject": bool(tail.at[ts, "svwap_reject"]),
            "bull_div": bool(tail.at[ts, "bull_div"]), "bear_div": bool(tail.at[ts, "bear_div"]),
        }
        for ts in tail.index
    ]

    return {
        "symbol": symbol,
        "tf": tf,
        "measurable": True,
        "source": source,
        "asof": bars.index[-1].isoformat(),
        "setup": {1: "bottom", -1: "top", 0: "none"}[cand],
        "missing_context": missing,
        "last": {
            "close": _f(last["close"]), "atr": _f(last["atr"]), "svwap": _f(last["svwap"]),
            "swing_dir": int(last["swing_dir"]), "svwap_dist_atr": _f(last["svwap_dist_atr"], 3),
            "poc": _f(last["poc"]), "val": _f(last["val"]), "vah": _f(last["vah"]),
            "poc_dist_atr": _f(last["poc_dist_atr"], 3), "rvol": _f(last["rvol"], 3),
            "macd": _f(last["macd_ha_c"], 2), "off_high_atr": _f(last["off_high_atr"], 3), "off_low_atr": _f(last["off_low_atr"], 3),
            "htf_macd": _f(last["htf_macd"], 2), "htf_range_pos": _f(last["htf_range_pos"], 3),
            "mkt_macd": _f(last["mkt_macd"], 2), "breadth_below": _f(last["breadth_below"], 3), "breadth_above": _f(last["breadth_above"], 3),
            "vol_regime": _f(last["vol_regime"], 3),
        },
        "reads": reads,
        "chart": chart,
        "study": study_meta(summary),
        "barrier": {"horizon_bars": cfg.horizon, "win_atr": cfg.win_atr, "loss_atr": cfg.loss_atr, "leg_atr": cfg.leg_atr},
    }


def study_meta(summary: dict | None) -> dict:
    if not summary:
        return {"available": False, "reason": "run `python -m edge.research.reversal_study --tf <tf>` to measure the signals"}
    return {
        "available": True,
        "version": summary.get("version"),
        "generated_at": summary.get("generated_at"),
        "symbols": summary.get("symbols"),
        "fit_period": summary.get("fit_period"),
        "validation_period": summary.get("validation_period"),
        "test_period": summary.get("test_period"),
        "trades_rule": summary.get("trades_rule"),
        "model_passes": {side: bool((s.get("model") or {}).get("passes")) for side, s in (summary.get("sides") or {}).items()},
    }


def scan_row(symbol: str, bars: pd.DataFrame, htf: pd.DataFrame, market: pd.DataFrame, tf: str, breadth: pd.DataFrame | None) -> dict | None:
    """One compact row for the scanner; None when the last bar is not in a
    qualifying leg."""
    cfg = study.CONFIGS[tf]
    summary, models = load_artifacts(tf)
    bars = _clean(bars)
    keep = 900 if tf == "1h" else 420
    bars = bars.iloc[-keep:]
    htf = rs.weekly_bars(bars) if tf == "1d" else _clean(htf)
    if len(bars) < 200 or len(htf) < 60:
        return None
    f = feature_frame(bars, htf, market, breadth, tf)
    last = f.iloc[-1]
    side = _candidate_side(last, cfg.leg_atr)
    if side == 0:
        return None
    name = "bottom" if side > 0 else "top"
    d = study.directional_frame(f.iloc[[-1]], side)
    ss = ((summary or {}).get("sides") or {}).get(name)
    prob, _ = _probability((models or {}).get(name), d, ss)
    rank = _model_rank((models or {}).get(name), d, ss)
    signals = _signal_rows(d.iloc[0], ss)
    triggers = _trigger_rows(f, side, summary, lookback=5)
    return {
        "symbol": symbol,
        "setup": name,
        "asof": bars.index[-1].isoformat(),
        "close": _f(last["close"]),
        "leg_atr": _f(-last["off_high_atr"] if side > 0 else last["off_low_atr"], 2),
        "svwap_dist_atr": _f(last["svwap_dist_atr"], 2),
        "poc_dist_atr": _f(last["poc_dist_atr"], 2),
        "macd": _f(last["macd_ha_c"], 1),
        "rvol": _f(last["rvol"], 2),
        "signals_on": [s["key"] for s in signals if s["on"]],
        "triggers_fired": [{"trigger": t["trigger"], "bars_ago": t["bars_ago"], "measured_edge": t["measured_edge"]} for t in triggers if t["fired"]],
        "probability": _f(prob, 4),
        "rank_tier": (rank or {}).get("tier"),
        "rank_tier_rate": (rank or {}).get("tier_rate"),
        "rank_tier_edge": (rank or {}).get("tier_edge"),
        "rank_score": (rank or {}).get("score"),
    }
