"""Volume Price Analysis (VPA) engine -- orchestrator.

This module composes the three modules that do the actual work and shapes the
API response. It deliberately contains **no scoring logic**:

* `research/vpa_bars.py`   -- timeframe-aware bar loading + `bars_meta` (D1)
* `research/vpa_levels.py` -- fractal pivots, zones, range-distributed VAP (D5/D6)
* `research/vpa_score.py`  -- signed evidence ledger -> probabilities (D4/D7)
* `research/vpa_thresholds.py` -- the single retunable threshold dict

What is left here: the Gemini vision prompt and call, the
image-vs-bars precedence (D2/D3), and the `/api/vpa/health` payload.

Contract: `docs/VPA_REBUILD_CONTRACT.md`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.vpa_codex import (
    VPA_CAMPAIGN_PHASES,
    VPA_CANDLE_TAXONOMY,
    VPA_CORE_PRINCIPLES,
    VPA_LAWS,
    VPA_MULTI_TIMEFRAME_MODEL,
    VPA_SUPPORT_RESISTANCE_RULES,
    get_full_vpa_codex,
)
from research.vpa_bars import (
    bar_is_complete,
    bars_meta_from_series,
    data_source_counts,
    load_bars,
    normalize_timeframe,
    symbol_timeframes,
    timeframe_availability,
)
from research.vpa_levels import (
    average_true_range,
    detect_congestion_patterns,
    detect_dynamic_trend,
    detect_levels,
    find_pivots,
)
from research.vpa_score import bar_metrics, score_evidence
from research.vpa_thresholds import BOOK_REFS, VPA_THRESHOLDS, book_spec_status

# Third-party published chart commentaries are not shipped.
SAMPLE_CHARTS: List[Dict[str, Any]] = []


def generate_vpa_system_prompt() -> str:
    """Instructions for an optional chart-image read. Original to this workstation."""
    return """You are reading one price chart for this workstation's volume-price engine.

Describe only what is visible: candle spread, wicks, and whether volume agrees with that spread.
Volume is effort. Spread is result. Agreement supports the move. Disagreement is a warning.
A wide advance on high volume supports the advance. A wide advance on low volume is weak participation.
A narrow bar on very high volume is effort without result.
Sideways time can precede a larger move, but do not invent a target the chart does not show.
Mark support and resistance as zones, not exact ticks. A level that was resistance can act as support
after a close through it on rising volume. A close beyond a zone on low volume is a failed break.
Name stopping or topping behavior only when wicks and volume both show it.
Always return a primary read and one alternative, with the price event that would invalidate the primary.

### OUTPUT FORMAT:
You MUST respond with pure, valid JSON conforming to the following structure (no markdown fences, no preamble):
{
  "symbol": "Detected or inferred symbol or 'CHART'",
  "timeframe": "Detected timeframe (e.g. '15m', 'Daily') or 'Unknown'",
  "asset_class": "equities | options | forex | crypto | futures | commodities",
  "market_phase": "Accumulation | Markup | Distribution | Markdown | Congestion",
  "dominant_sentiment": "Bullish | Bearish | Neutral / Indecision",
  "confidence_score": 0.85,
  "effort_vs_result_verdict": "VALIDATION | ANOMALY | MIXED",
  "forensic_breakdown": {
    "wyckoff_phase": "Campaign phase visible on the chart",
    "key_candles": [
      {
        "candle_type": "Shooting Star | Hammer | Doji | Wide Spread Up | Narrow Spread etc.",
        "spread": "Wide | Narrow | Average",
        "volume": "Ultra High | High | Average | Low",
        "verdict": "VALIDATION or ANOMALY",
        "interpretation": "What spread and volume show on this bar"
      }
    ],
    "stopping_or_topping": {
      "detected": true,
      "type": "Stopping Volume | Topping Out Volume | None",
      "details": "What the wicks and volume show"
    },
    "test_candles": {
      "detected": true,
      "type": "Low Volume Supply Test | Low Volume Demand Test | None",
      "result": "Successful | Failed | None"
    },
    "support_resistance": {
      "floor_support": "Floor level / price zone",
      "ceiling_resistance": "Ceiling level / price zone",
      "pivot_highs": "Observed pivot highs",
      "pivot_lows": "Observed pivot lows"
    },
    "volume_at_price": "Horizontal volume observations if visible"
  },
  "primary_scenario": {
    "likely_move": "Concise scenario summary",
    "direction": "BULLISH | BEARISH | SIDEWAYS",
    "probability_pct": 75,
    "target_zone": "Estimated target price zone",
    "expected_horizon": "Estimated time horizon",
    "rationale": "Why volume and spread support this read"
  },
  "alternative_scenarios": [
    {
      "thesis": "Alternative interpretation",
      "probability_pct": 25,
      "speculative_read": "Counter-thesis",
      "invalidation_trigger": "Price or volume event that invalidates the primary read",
      "risk_warning": "What would make the read fail"
    }
  ],
  "trade_execution_guide": {
    "bias": "LONG | SHORT | NEUTRAL / WAIT",
    "entry_trigger": "Candle and volume trigger",
    "stop_loss_placement": "Placement beyond the zone or wick that defines the idea",
    "risk_reward_ratio": "e.g. 1 : 3.0",
    "rules_applied": [
      "Names of the engine rules used"
    ]
  }
}
"""


def call_gemini_vision(
    image_base64: str,
    mime_type: str = "image/png",
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Invokes Gemini Multimodal Vision to perform Volume Price Analysis on a chart."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("No GEMINI_API_KEY or GOOGLE_API_KEY found in environment.")

    # Clean base64 data header if included
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    prompt_text = generate_vpa_system_prompt()
    user_context = ""
    if symbol:
        user_context += f"Symbol: {symbol}\n"
    if timeframe:
        user_context += f"Timeframe: {timeframe}\n"
    if notes:
        user_context += f"Operator Notes: {notes}\n"
    if user_context:
        prompt_text += f"\n\n### ADDITIONAL USER CONTEXT:\n{user_context}"

    prompt_text += "\n\nAnalyze the attached chart screenshot. Return ONLY the JSON object."

    # First try google.genai SDK if available
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        image_bytes = base64.b64decode(image_base64)

        model_name = os.environ.get("EDGE_VPA_MODEL", "gemini-2.5-flash")

        response = client.models.generate_content(
            model=model_name,
            contents=[
                prompt_text,
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
        )

        raw_text = response.text or ""
        return _clean_and_parse_json(raw_text)

    except Exception as sdk_err:
        models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
        last_err = sdk_err

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            req_body = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt_text},
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": image_base64,
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(req_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    candidates = resp_data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text", "")
                            return _clean_and_parse_json(raw_text)
            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(f"Gemini Vision API request failed: {last_err}")


def _clean_and_parse_json(raw_text: str) -> Dict[str, Any]:
    """Extracts JSON block from model response."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Could not parse valid JSON from AI response: {raw_text[:200]}...")


def _normalize_series(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Accept both the `/api/trajectory` short keys and full OHLCV names."""
    clean: List[Dict[str, Any]] = []
    for row in series or []:
        o = row.get("o") if row.get("o") is not None else row.get("open")
        h = row.get("h") if row.get("h") is not None else row.get("high")
        l = row.get("l") if row.get("l") is not None else row.get("low")
        c = row.get("c") if row.get("c") is not None else row.get("close")
        v = row.get("v") if row.get("v") is not None else row.get("volume")
        d = row.get("d") if row.get("d") is not None else row.get("date")
        if o is None or h is None or l is None or c is None:
            continue
        try:
            o, h, l, c = float(o), float(h), float(l), float(c)
            v = float(v or 0.0)
        except (TypeError, ValueError):
            continue
        if not (h >= l and h > 0):
            continue
        clean.append({"date": str(d or ""), "open": o, "high": h, "low": l, "close": c, "volume": v})

    # If the series was supplied in reverse-chronological order (newest first,
    # common in REST APIs), reverse it to chronological ascending order so
    # indicators and canvas evaluate time forward.
    if len(clean) >= 2:
        d_first = str(clean[0].get("date") or "")
        d_last = str(clean[-1].get("date") or "")
        if d_first and d_last and d_first > d_last:
            if all(str(clean[i].get("date") or "") >= str(clean[i + 1].get("date") or "") for i in range(len(clean) - 1)):
                clean.reverse()

    return clean


def _short_label(date_str: str) -> str:
    if not date_str:
        return ""
    if "T" in date_str:
        day, _, clock = date_str.partition("T")
        return f"{day[5:]} {clock[:5]}"
    return date_str[:10]


def _classify_key_candles(bars: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    """Bar-by-bar volume and spread labels for the last `limit` bars.

    Kept as prose for the existing UI panel, but every label is now backed by
    the same relative volume/spread ratios the evidence ledger uses, and the
    ratios are printed so the reader can check the call.
    """
    cfg = VPA_THRESHOLDS["signals"]
    metrics = bar_metrics(bars)
    out: List[Dict[str, Any]] = []
    for m in metrics[-limit:]:
        rng, vr, sr = m["range"], m["vol_ratio"], m["spread_ratio"]
        if rng <= 0:
            continue
        up_frac = m["upper_wick"] / rng
        low_frac = m["lower_wick"] / rng
        body_frac = m["body"] / rng

        if vr >= cfg["vol_ultra_high"]:
            vol_label = "Ultra High"
        elif vr >= cfg["vol_high"]:
            vol_label = "High"
        elif vr and vr <= cfg["vol_ultra_low"]:
            vol_label = "Ultra Low"
        elif vr and vr <= cfg["vol_low"]:
            vol_label = "Low"
        else:
            vol_label = "Average"

        if sr >= cfg["spread_wide"]:
            spread_label = "Wide"
        elif sr and sr <= cfg["spread_narrow"]:
            spread_label = "Narrow"
        else:
            spread_label = "Average"

        if low_frac >= cfg["wick_dominant"] and up_frac <= cfg["wick_suppressed"]:
            c_type = "Hammer Candle"
        elif up_frac >= cfg["wick_dominant"] and low_frac <= cfg["wick_suppressed"]:
            c_type = "Shooting Star"
        elif body_frac <= cfg["doji_body"] and up_frac >= 0.30 and low_frac >= 0.30:
            c_type = "Long-Legged Doji"
        elif spread_label == "Wide":
            c_type = "Wide Spread Up" if m["is_up"] else "Wide Spread Down"
        elif spread_label == "Narrow":
            c_type = "Narrow Spread Bar"
        else:
            c_type = "Standard Spread"

        # Effort (volume) vs result (spread): agreement validates, disagreement
        # is the anomaly the engine scores (effort without a matching spread).
        effort_high = vr >= cfg["vol_high"]
        result_wide = sr >= cfg["spread_wide"]
        result_narrow = sr and sr <= cfg["spread_narrow"]
        if effort_high and result_narrow:
            verdict = "ANOMALY (Absorption)"
            interp = f"{vr:.1f}x volume produced only a {sr:.2f}x spread: one side is absorbing the other."
        elif (not effort_high) and result_wide:
            verdict = "ANOMALY (Effort Missing)"
            interp = f"A {sr:.1f}x spread on only {vr:.2f}x volume: result without effort behind it."
        elif effort_high and result_wide:
            verdict = "VALIDATION (Effort = Result)"
            interp = f"{sr:.1f}x spread matched by {vr:.1f}x volume: the move is genuine."
        else:
            verdict = "VALIDATION"
            interp = f"Effort ({vr:.2f}x volume) and result ({sr:.2f}x spread) in normal proportion."

        out.append({
            "candle_type": f"{c_type} ({_short_label(m['date'])})",
            "spread": f"{spread_label} ({rng:.2f})",
            "volume": f"{vol_label} ({vr:.1f}x)" if vr else f"{vol_label} (no baseline)",
            "verdict": verdict,
            "interpretation": interp,
            "bar": m["i"],
        })
    return out


def _market_phase(direction: str, bars: List[Dict[str, Any]], scored: Dict[str, Any]) -> str:
    """Wyckoff phase read from volume behaviour over the window the signals
    were actually scanned in (Ch.2, Ch.11).

    Position inside a price box is not a phase, and the box has to be the same
    one the read came from. Measuring position over 60 bars while signals are
    scanned over 20 let a spike that had already rolled off the read name the
    phase -- which is how a +30% 20-bar bullish read came back labelled
    "Accumulation (lower half of range)".
    """
    cfg = VPA_THRESHOLDS["signals"]
    scan = int(cfg["scan_window"])
    window = bars[-min(len(bars), scan):]
    cause = scored["cause_bars"]
    if direction == "SIDEWAYS":
        return f"Congestion / Cause Building ({cause} bars inside the value area)"

    hi = max(b["high"] for b in window)
    lo = min(b["low"] for b in window)
    pos = ((bars[-1]["close"] - lo) / (hi - lo)) if hi > lo else 0.5
    travelled = abs(window[-1]["close"] - window[0]["close"])
    atr = average_true_range(bars)
    if atr > 0 and travelled / atr >= float(cfg["trend_move_atr"]):
        # A window that has actually travelled is a campaign in progress, not
        # a base being built.
        return (
            "Markup Phase (Demand in Control)"
            if direction == "BULLISH"
            else "Markdown Phase (Supply in Control)"
        )

    # Range-bound: the phase is decided by which side's volume is drying up.
    up = [b["volume"] for b in window if b["close"] > b["open"]]
    down = [b["volume"] for b in window if b["close"] < b["open"]]
    up_avg = (sum(up) / len(up)) if up else 0.0
    down_avg = (sum(down) / len(down)) if down else 0.0
    where = f"{pos:.0%} of the {scan}-bar range"

    if direction == "BULLISH":
        if down_avg and up_avg >= down_avg:
            # Sellers withdrawing under a range is the book's accumulation;
            # the same behaviour high in a range is re-accumulation.
            base = "Accumulation" if pos < 0.4 else "Re-accumulation"
            return f"{base} (supply drying, {where})"
        return f"Range / supply still present ({where})"
    if up_avg and down_avg >= up_avg:
        base = "Distribution" if pos > 0.6 else "Re-distribution"
        return f"{base} (demand drying, {where})"
    return f"Range / demand still present ({where})"


def _sentiment(direction: str, pct: int) -> str:
    if direction == "SIDEWAYS":
        return "Neutral / Two-Sided"
    strong = "Strongly " if pct >= 70 else ("" if pct >= 58 else "Mildly ")
    return f"{strong}{'Bullish' if direction == 'BULLISH' else 'Bearish'}"


def _fmt(value: Optional[float]) -> str:
    return f"${value:,.2f}" if isinstance(value, (int, float)) else "—"


def _vision_model() -> str:
    return os.environ.get("EDGE_VPA_MODEL", "gemini-2.5-flash")


def vision_available() -> bool:
    """Is any chart-vision backend reachable?

    Two auth paths are accepted. An API key is the simple one; the repo also
    carries Vertex tooling and gcloud application-default credentials, so ADC
    counts too and needs no key pasted into `.env`.

    Vision is deliberately optional. It exists only to read a chart we hold no
    bars for -- for anything in the local universe the quantitative path is
    both available and more precise, because it works on the exact OHLCV
    values instead of inferring candle geometry from pixels.
    """
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return True
    if os.environ.get("EDGE_VPA_DISABLE_VERTEX"):
        return False
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project:
        return False
    adc = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if adc and Path(adc).is_file():
        return True
    default_adc = (
        Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    )
    return default_adc.is_file()


def _vision_status(
    image_base64: Optional[str],
    image_used: bool = False,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Contract §4: say what happened to the image instead of dropping it.

    D2/D3: the old entrypoint tested `ohlcv_series` before `image_base64`, and
    the UI always posts bars alongside a snapshot, so the image was discarded
    with no warning and the response still claimed a quantitative read. There
    is also no `GEMINI_API_KEY`/`GOOGLE_API_KEY` in `.env`, so vision is
    currently unavailable -- which the UI must be able to say out loud.
    """
    available = vision_available()
    if reason is None and not available:
        reason = (
            "No chart-vision model configured. Not required: the engine reads "
            "exact OHLCV bars, which is strictly more precise than inferring "
            "candles from pixels. Vision only adds value for a chart we hold "
            "no data for."
        )
    return {
        "available": available,
        # Vision is an optional enrichment, never a prerequisite. The
        # quantitative path is primary and is the more accurate of the two.
        "required": False,
        "primary_path": "quantitative_ohlcv_vpa",
        "reason": reason,
        "image_received": bool(image_base64),
        "image_used": bool(image_used),
        "model": _vision_model() if available else None,
    }


def evaluate_ohlcv_series(
    series: List[Dict[str, Any]],
    symbol: str,
    timeframe: str = "1D",
    asset_class: str = "equities",
    notes: Optional[str] = None,
    bars_meta: Optional[Dict[str, Any]] = None,
    extra_evidence: Optional[List[Dict[str, Any]]] = None,
    vision_status: Optional[Dict[str, Any]] = None,
    engine_mode: str = "quantitative_ohlcv_vpa",
    display_only_evidence: Optional[List[Dict[str, Any]]] = None,
    deterministic: bool = True,
) -> Dict[str, Any]:
    """Forensic quantitative VPA over real bars, with every number derived.

    Composes `vpa_levels.detect_levels` (D5/D6) and `vpa_score.score_evidence`
    (D4/D7). No scoring logic lives here -- this function only shapes the
    contract §4 response.

    `extra_evidence` is fed into `score_evidence` and therefore *moves*
    `primary_probability_pct` / `confidence_score` (D1: only the explicit
    fused-vision opt-in should ever pass a non-deterministic item here).
    `display_only_evidence` is appended to the response's `evidence` list
    *after* scoring -- it is shown to the reader but never touches the
    scored numbers, which is how the default (non-opt-in) vision read is
    surfaced without making the ledger non-reproducible. `deterministic`
    is stamped onto the response verbatim (and mirrored as `reproducible`)
    so no consumer can mistake a run that included a non-deterministic
    input (e.g. fused vision) for a byte-reproducible one.
    """
    bars = _normalize_series(series)
    meta = bars_meta or bars_meta_from_series(bars, timeframe)
    min_bars = int(VPA_THRESHOLDS["bars"]["min_bars_for_analysis"])
    if len(bars) < min_bars:
        return _no_data_response(
            symbol=symbol,
            timeframe=timeframe,
            asset_class=asset_class,
            bars_meta=meta,
            vision_status=vision_status,
            reason=(
                f"only {len(bars)} usable bars; VPA needs at least {min_bars} to read volume "
                "relative to previous bars"
            ),
        )

    levels = detect_levels(bars)
    # Trend lines and congestion patterns are measured from pivots.
    _pivots = find_pivots(bars)
    dynamic_trend = detect_dynamic_trend(bars, _pivots)
    congestion_patterns = detect_congestion_patterns(bars, _pivots)
    scored = score_evidence(bars, levels, meta, extra_evidence=extra_evidence)

    direction = scored["direction"]
    primary_pct = scored["primary_probability_pct"]
    plan = scored["trade_plan"]
    vap = levels.get("vap")
    support = levels.get("nearest_support")
    resistance = levels.get("nearest_resistance")
    last_price = bars[-1]["close"]
    tf_label = meta.get("timeframe_label") or meta.get("timeframe_served") or timeframe
    n = len(bars)

    rules_applied: List[str] = []
    for item in scored["evidence"]:
        if item["book_ref"] not in rules_applied:
            rules_applied.append(item["book_ref"])
    if not rules_applied:
        rules_applied = ["No volume-price signal fired in the scanned window"]

    if direction == "BULLISH":
        bias = "LONG"
        alt_thesis = "Supply returns at the ceiling / failed markup"
        alt_read = (
            f"If price stalls at {_fmt(resistance['price'] if resistance else None)} on ultra-high "
            "volume with narrow spreads and deep upper wicks, the advance is being distributed into "
            "rather than driven by demand."
        )
        invalidation = (
            f"Close below {_fmt(support['low'] if support else None)} on volume above "
            f"{VPA_THRESHOLDS['levels']['breakout_volume_ratio']}x the 20-bar average."
            if support else "No confirmed support band in the window to invalidate against."
        )
    elif direction == "BEARISH":
        bias = "SHORT"
        alt_thesis = "Stopping volume ends the markdown"
        alt_read = (
            f"If a bar prints ultra-high volume with a deep lower wick near "
            f"{_fmt(support['price'] if support else None)} and closes in its upper half, insiders are "
            "absorbing the liquidation and the markdown is over."
        )
        invalidation = (
            f"Close above {_fmt(resistance['high'] if resistance else None)} on volume above "
            f"{VPA_THRESHOLDS['levels']['breakout_volume_ratio']}x the 20-bar average."
            if resistance else "No confirmed resistance band in the window to invalidate against."
        )
    else:
        bias = "NEUTRAL / WAIT"
        alt_thesis = "Range resolves with a volume-backed breakout"
        alt_read = (
            "The ledger is balanced. The next directional read comes from which band breaks with "
            "a close beyond the zone on rising volume, not from the current bars."
        )
        invalidation = (
            f"Clear-water close outside {_fmt(support['low'] if support else None)} - "
            f"{_fmt(resistance['high'] if resistance else None)} on rising volume."
        )

    cause = scored["cause_bars"]
    target_zone = (
        f"{_fmt(plan['target'])} ({plan['target_basis']})" if plan["target"] is not None
        else "— (no confirmed level to target in this window)"
    )

    return {
        "symbol": str(symbol).upper(),
        "timeframe": meta.get("timeframe_served") or timeframe,
        "timeframe_requested": meta.get("timeframe_requested", timeframe),
        "asset_class": asset_class,
        "market_phase": _market_phase(direction, bars, scored),
        "dominant_sentiment": _sentiment(direction, primary_pct),
        "confidence_score": scored["confidence"]["confidence_score"],
        "confidence_basis": scored["confidence"],
        "effort_vs_result_verdict": scored["effort_vs_result_verdict"],
        "forensic_breakdown": {
            "wyckoff_phase": (
                f"{str(symbol).upper()} at {_fmt(last_price)} on {tf_label} bars. "
                f"{cause} bars of cause built inside the value area "
                f"{_fmt(vap['value_area_low']) if vap else '—'} - "
                f"{_fmt(vap['value_area_high']) if vap else '—'}; "
                f"{len(levels['levels'])} confirmed pivot-cluster bands across {n} bars."
            ),
            "key_candles": _classify_key_candles(bars),
            "stopping_or_topping": scored["stopping_or_topping"],
            "test_candles": scored["test_candles"],
            "support_resistance": {
                "floor_support": (
                    f"{_fmt(support['price'])} band {_fmt(support['low'])}-{_fmt(support['high'])} "
                    f"({support['touches']} touches, strength {support['strength']})"
                    if support else "— (no confirmed support band in window)"
                ),
                "ceiling_resistance": (
                    f"{_fmt(resistance['price'])} band {_fmt(resistance['low'])}-{_fmt(resistance['high'])} "
                    f"({resistance['touches']} touches, strength {resistance['strength']})"
                    if resistance else "— (no confirmed resistance band in window)"
                ),
                "pivot_highs": ", ".join(
                    _fmt(z["price"]) for z in levels["levels"] if z["origin"] == "resistance"
                ) or "—",
                "pivot_lows": ", ".join(
                    _fmt(z["price"]) for z in levels["levels"] if z["origin"] == "support"
                ) or "—",
                "method": (
                    f"{VPA_THRESHOLDS['levels']['pivot_left']}-bar fractal pivots clustered at "
                    f"{VPA_THRESHOLDS['levels']['cluster_atr_mult']}x ATR, decayed by recency"
                ),
            },
            "volume_at_price": (
                f"POC {_fmt(vap['poc'])}; 70% value area {_fmt(vap['value_area_low'])}-"
                f"{_fmt(vap['value_area_high'])}. Each bar's volume distributed across its high-low "
                "range, not binned at its close."
                if vap else "— (no volume distribution available)"
            ),
        },
        "primary_scenario": {
            "likely_move": (
                f"{direction.title()} continuation toward {target_zone}" if direction != "SIDEWAYS"
                else "Range-bound; wait for a volume-backed break of either band"
            ),
            "direction": direction,
            "probability_pct": primary_pct,
            "target_zone": target_zone,
            "expected_horizon": (
                f"{max(2, cause // 2)} to {max(4, cause)} {tf_label} bars "
                "(Law of Cause & Effect: effect scales with the cause built)"
            ),
            "rationale": (
                "; ".join(f"{e['signal']} ({e['direction']}, w={e['weight']})"
                          for e in scored["evidence"][:4])
                or "No volume-price signal fired in the scanned window."
            ),
        },
        "alternative_scenarios": [
            {
                "thesis": alt_thesis,
                "probability_pct": scored["alternative_probability_pct"],
                "speculative_read": alt_read,
                "invalidation_trigger": invalidation,
                "risk_warning": (
                    "A breakout without rising volume is a fakeout: never anticipate the break "
                    "before the volume confirms institutional commitment."
                ),
            }
        ],
        "trade_execution_guide": {
            "bias": bias,
            "entry_trigger": (
                f"Entry reference {_fmt(plan['entry'])} (last close). Wait for a "
                "low-volume retest of the band or a close beyond it on rising volume."
            ),
            "stop_loss_placement": (
                f"{_fmt(plan['stop'])} — {plan['stop_basis']}" if plan["stop"] is not None
                else "— (no level available to place a stop against)"
            ),
            "risk_reward_ratio": plan["risk_reward_ratio"],
            "risk_reward_unavailable_reason": plan["unavailable_reason"],
            "entry_price": plan["entry"],
            "stop_price": plan["stop"],
            "target_price": plan["target"],
            "rules_applied": rules_applied[:6],
        },
        "bars": [
            {
                "d": str(b.get("date") or ""),
                "o": float(b["open"]),
                "h": float(b["high"]),
                "l": float(b["low"]),
                "c": float(b["close"]),
                "v": float(b.get("volume", 0.0)),
            }
            for b in bars
        ],
        "bars_meta": meta,
        "levels": levels["levels"],
        "vap": vap,
        "dynamic_trend": dynamic_trend,
        "congestion_patterns": congestion_patterns,
        "atr": levels["atr"],
        "evidence": scored["evidence"] + list(display_only_evidence or []),
        "probability_basis": scored["probability_basis"],
        "vision_status": vision_status or _vision_status(None),
        "thresholds_status": book_spec_status(),
        "engine_mode": engine_mode,
        "is_sample": False,
        # D1: byte-for-byte reproducibility contract. True unless a
        # non-deterministic input (e.g. an LLM vision read, opted into the
        # scored ledger) fed the numbers above.
        "deterministic": deterministic,
        "reproducible": deterministic,
    }


def _no_data_response(
    symbol: Optional[str],
    timeframe: Optional[str],
    asset_class: Optional[str],
    bars_meta: Optional[Dict[str, Any]] = None,
    vision_status: Optional[Dict[str, Any]] = None,
    reason: str = "no bars available",
    deterministic: bool = True,
) -> Dict[str, Any]:
    """The honest empty read.

    Contract §1.1: a missing number renders as an em dash, never as a plausible
    constant. The old fallback invented a full analysis -- 0.76 confidence,
    68/32 probabilities, `test_candles.detected: True` -- for a symbol it had
    never loaded a single bar for. Nothing here is invented: every numeric field
    is `None` and the response says why.
    """
    sym = (symbol or "MARKET").upper()
    meta = bars_meta or {
        "timeframe_requested": timeframe or "1D",
        "timeframe_served": None,
        "downgraded": False,
        "downgrade_reason": reason,
        "bar_count": 0,
        "first_bar": None,
        "last_bar": None,
        "source": None,
        "available": False,
    }
    return {
        "symbol": sym,
        "timeframe": timeframe or "1D",
        "timeframe_requested": timeframe or "1D",
        "asset_class": asset_class or "equities",
        "market_phase": "Unknown — no bars analysed",
        "bars": [],
        "dominant_sentiment": "Unknown",
        "confidence_score": None,
        "confidence_basis": {"confidence_score": None, "components": {}, "method": "not computed"},
        "effort_vs_result_verdict": "UNKNOWN",
        "data_status": {"analysed": False, "reason": reason},
        "forensic_breakdown": {
            "wyckoff_phase": f"No bars loaded for {sym}: {reason}.",
            "key_candles": [],
            "stopping_or_topping": {
                "detected": False,
                "type": "None",
                "details": f"Not evaluated — {reason}.",
                "bars": [],
                "book_ref": BOOK_REFS["stopping_volume"],
            },
            "test_candles": {
                "detected": False,
                "type": "None",
                "result": "None",
                "details": f"Not evaluated — {reason}.",
                "bars": [],
                "book_ref": BOOK_REFS["testing"],
            },
            "support_resistance": {
                "floor_support": "—",
                "ceiling_resistance": "—",
                "pivot_highs": "—",
                "pivot_lows": "—",
                "method": "not computed",
            },
            "volume_at_price": "—",
        },
        "primary_scenario": {
            "likely_move": "Not computed — no bars",
            "direction": "UNKNOWN",
            "probability_pct": None,
            "target_zone": "—",
            "expected_horizon": "—",
            "rationale": reason,
        },
        "alternative_scenarios": [
            {
                "thesis": "Not computed — no bars",
                "probability_pct": None,
                "speculative_read": reason,
                "invalidation_trigger": "Not available without bars to analyse.",
                "risk_warning": "No analysis was produced; do not trade from this response.",
            }
        ],
        "trade_execution_guide": {
            "bias": "NO READ",
            "entry_trigger": "—",
            "stop_loss_placement": "—",
            "risk_reward_ratio": None,
            "risk_reward_unavailable_reason": reason,
            "entry_price": None,
            "stop_price": None,
            "target_price": None,
            "rules_applied": [],
        },
        "bars_meta": meta,
        "levels": [],
        "vap": None,
        "atr": None,
        "evidence": [],
        "probability_basis": {
            "bull_score": 0.0,
            "bear_score": 0.0,
            "method": "not computed",
            "band": [
                100 - VPA_THRESHOLDS["scoring"]["probability_ceiling"],
                VPA_THRESHOLDS["scoring"]["probability_ceiling"],
            ],
            "evidence_count": 0,
            "note": reason,
        },
        "vision_status": vision_status or _vision_status(None),
        "thresholds_status": book_spec_status(),
        "engine_mode": "offline_heuristic",
        "is_sample": False,
        "deterministic": deterministic,
        "reproducible": deterministic,
    }


def _vision_evidence(vision_json: Dict[str, Any], contributes_to_score: bool) -> List[Dict[str, Any]]:
    """Turn the vision model's directional read into one ledger item.

    D1: an LLM's output is not reproducible, so this item is only ever fed
    into `score_evidence` (i.e. allowed to move `primary_probability_pct` /
    `confidence_score`) when the caller has explicitly opted into the fused,
    non-deterministic mode. Otherwise it is still returned here so it can be
    appended to the response's `evidence` list as a *display-only* entry --
    visible to the reader, but never scored -- via `contributes_to_score`.
    """
    primary = (vision_json or {}).get("primary_scenario") or {}
    direction = str(primary.get("direction", "")).upper()
    if direction not in {"BULLISH", "BEARISH"}:
        return []
    detail = str(primary.get("rationale") or primary.get("likely_move") or "Vision read of the chart image.")
    scored_note = (
        "counted toward the scored probability/confidence (fused-vision opt-in active)"
        if contributes_to_score
        else "qualitative only -- NOT counted toward the scored probability/confidence"
    )
    return [{
        "signal": "vision_agreement",
        "direction": "bullish" if direction == "BULLISH" else "bearish",
        "weight": round(float(VPA_THRESHOLDS["weights"]["vision_agreement"]), 4),
        "bars": [],
        "bar_dates": [],
        "book_ref": BOOK_REFS["vision_agreement"],
        "detail": f"Vision model read of the supplied chart image: {detail[:400]} ({scored_note}).",
        "contributes_to_score": contributes_to_score,
    }]


def _attach_vision_read(
    vision_json: Dict[str, Any],
    quantitative_direction: Optional[str],
    vision_status: Dict[str, Any],
) -> None:
    """Add D1's qualitative disclosure fields to the raw vision payload.

    Mutates `vision_json` **in place** rather than building a new dict, so
    that a caller (or a test) holding the same reference the mocked vision
    backend returned still sees an object `==` to what the model produced --
    the response's `vision_read` field always carries this same object.
    """
    primary = (vision_json or {}).get("primary_scenario") or {}
    v_direction = str(primary.get("direction", "")).upper() or None
    if v_direction not in {"BULLISH", "BEARISH"}:
        v_direction = None
    agrees_with_quantitative = None
    if v_direction is not None and quantitative_direction in {"BULLISH", "BEARISH"}:
        agrees_with_quantitative = v_direction == quantitative_direction
    vision_json["direction"] = v_direction
    vision_json["rationale"] = primary.get("rationale") or primary.get("likely_move")
    vision_json["model"] = vision_status.get("model")
    vision_json["agrees_with_quantitative"] = agrees_with_quantitative


def analyze_chart_vpa(
    image_base64: Optional[str] = None,
    mime_type: str = "image/png",
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    asset_class: Optional[str] = None,
    notes: Optional[str] = None,
    sample_id: Optional[str] = None,
    ohlcv_series: Optional[List[Dict[str, Any]]] = None,
    lookback: Optional[int] = None,
    fuse_vision_into_score: bool = False,
) -> Dict[str, Any]:
    """High-level entrypoint for Volume Price Analysis.

    Precedence (D2 fix): the image is checked **before** the bar series. The old
    order tested `ohlcv_series` first, and since the UI always posts bars
    alongside a snapshot the image was silently discarded -- confirmed live,
    image+bars returned `engine_mode: quantitative_ohlcv_vpa` with no warning.
    Now: image + vision available + bars -> both run (`vision+quant`); image +
    vision available, no bars -> `vision_multimodal`; image but vision
    unavailable -> the quantitative read still runs, and `vision_status` says
    the image was received and not used, and why.

    D1 (reproducibility): an LLM's directional read of a chart image is not
    reproducible, so it NEVER moves `primary_probability_pct` or
    `confidence_score` by default. In `vision+quant` mode the vision read is
    always returned as its own qualitative block (`vision_read`, with
    `direction` / `rationale` / `model` / `agrees_with_quantitative`) and is
    listed in `evidence` for transparency, but the scored numbers are computed
    from bars alone -- the response is stamped `deterministic: true`. Pass
    `fuse_vision_into_score=True` to opt into the old behaviour, where the
    vision read is summed into the same weighted ledger that produces the
    probability/confidence; that response is stamped `deterministic: false`,
    `reproducible: false`. An image-only request (no bars) has nothing but
    the vision read to go on, so it is always non-deterministic regardless of
    this flag.
    """
    if sample_id:
        match = next((s for s in SAMPLE_CHARTS if s["id"] == sample_id), None)
        if match is not None:
            res = dict(match["analysis"])
            res["is_sample"] = True
            res["sample_title"] = match.get("title")
            res["description"] = match.get("description")
            res["engine_mode"] = "stored_reference"
            res["source_attribution"] = "Stored reference case. Not a live computation."
            res["computed_by_engine"] = False
            res["vision_status"] = _vision_status(None, reason="stored reference; no analysis run")
            res["deterministic"] = True
            res["reproducible"] = True
            return res

    # 1. Load the bars the *requested timeframe* actually implies (D1). The UI
    #    posts a daily series regardless of the selector, so a client-supplied
    #    series is only used when we cannot back the symbol ourselves.
    bars: List[Dict[str, Any]] = []
    meta: Optional[Dict[str, Any]] = None
    if symbol:
        bars, meta = load_bars(symbol, timeframe, lookback)
    if not bars and ohlcv_series:
        bars = _normalize_series(ohlcv_series)
        # Client bars carry no reliable timezone, so only the date-level check
        # is safe: a daily/weekly bar dated today is still forming until the close.
        if bars and normalize_timeframe(timeframe) in ("1D", "1W") and not bar_is_complete(
            bars[-1].get("date", ""), normalize_timeframe(timeframe)
        ):
            bars = bars[:-1]
        meta = bars_meta_from_series(
            bars,
            timeframe,
            reason=(
                "no local parquet for this symbol/timeframe; analysed the bar series supplied by "
                "the client, whose true granularity is unverified"
            ),
        )

    has_key = vision_available()

    # 2. Image first when vision is actually available.
    if image_base64 and has_key:
        try:
            vision = call_gemini_vision(
                image_base64=image_base64,
                mime_type=mime_type,
                symbol=symbol,
                timeframe=timeframe,
                notes=notes,
            )
        except Exception as err:  # noqa: BLE001 - surfaced to the caller verbatim
            status = _vision_status(image_base64, image_used=False, reason=f"vision call failed: {err}")
            if bars:
                return evaluate_ohlcv_series(
                    series=bars, symbol=symbol or "CHART", timeframe=timeframe or "1D",
                    asset_class=asset_class or "equities", notes=notes, bars_meta=meta,
                    vision_status=status,
                )
            return _no_data_response(symbol, timeframe, asset_class, meta, status,
                                     reason=f"vision call failed and no bars available: {err}")

        status = _vision_status(image_base64, image_used=True)
        if bars:
            vision_evidence = _vision_evidence(vision, contributes_to_score=fuse_vision_into_score)
            fused = evaluate_ohlcv_series(
                series=bars, symbol=symbol or "CHART", timeframe=timeframe or "1D",
                asset_class=asset_class or "equities", notes=notes, bars_meta=meta,
                extra_evidence=vision_evidence if fuse_vision_into_score else None,
                display_only_evidence=None if fuse_vision_into_score else vision_evidence,
                vision_status=status,
                engine_mode="vision+quant",
                deterministic=not fuse_vision_into_score,
            )
            _attach_vision_read(vision, fused["primary_scenario"]["direction"], status)
            fused["vision_read"] = vision
            return fused
        # Image-only: there are no bars to fall back on, so the *entire*
        # response is the vision model's read -- always non-deterministic,
        # regardless of `fuse_vision_into_score`.
        _attach_vision_read(vision, None, status)
        vision["is_sample"] = False
        vision["engine_mode"] = "vision_multimodal"
        vision["vision_status"] = status
        vision["bars_meta"] = meta or bars_meta_from_series([], timeframe, reason="image-only request")
        vision["thresholds_status"] = book_spec_status()
        vision["deterministic"] = False
        vision["reproducible"] = False
        return vision

    # 3. Quantitative read. If an image came in but vision is off, say so
    #    rather than pretending the snapshot did something (D3).
    status = _vision_status(image_base64, image_used=False)
    if image_base64:
        # A pasted chart is never silently swallowed. When we hold bars for the
        # symbol we say plainly that the exact-bar read superseded the image,
        # because pixel inference is the weaker of the two.
        status["reason"] = (
            "Image received and kept as visual reference. The forensic read "
            "was computed from exact OHLCV bars, which is more precise than "
            "reading candles off a screenshot."
            if bars
            else status["reason"]
        )

    if bars:
        return evaluate_ohlcv_series(
            series=bars, symbol=symbol or "CHART", timeframe=timeframe or "1D",
            asset_class=asset_class or "equities", notes=notes, bars_meta=meta,
            vision_status=status,
        )

    reason = (meta or {}).get("downgrade_reason") or "no bars available for this symbol and timeframe"
    res = _no_data_response(symbol, timeframe, asset_class, meta, status, reason=reason)
    res["notice"] = (
        f"No local bars for this symbol and timeframe. {_UNIVERSE_HINT}"
        if not has_key
        else "No local bars for this symbol and timeframe; paste a chart image to read it with vision."
    )
    return res


_UNIVERSE_HINT = (
    "Enter a symbol carried in data/1d, data/1d_wide or data/1h. "
    "Chart-image reading is optional and is not needed for any symbol we hold."
)


def vpa_health(symbol: Optional[str] = None) -> Dict[str, Any]:
    """Payload for `GET /api/vpa/health` (contract §4).

    The frontend builds its timeframe dropdown from this instead of a hardcoded
    array, so an unbacked timeframe is disabled with its reason shown rather
    than silently substituted.
    """
    has_key = vision_available()
    counts = data_source_counts()

    # Per-symbol truth. Without this the dropdown offers 1h for a symbol that
    # has no hourly parquet, and the user only discovers the downgrade after
    # the request comes back -- the exact "looks like it worked" failure this
    # rebuild exists to remove.
    frames = timeframe_availability()
    if symbol:
        supported = symbol_timeframes(symbol)
        sym = (symbol or "").strip().upper()
        for entry in frames:
            if not entry["available"]:
                continue
            if not supported.get(entry["value"], False):
                entry["available"] = False
                entry["reason"] = (
                    f"no hourly bars on disk for {sym}"
                    if entry.get("source", "").startswith("data/1h")
                    else f"no local bars for {sym}"
                )

    return {
        "symbol": (symbol or "").strip().upper() or None,
        "vision": {
            "available": has_key,
            "required": False,
            "primary_path": "quantitative_ohlcv_vpa",
            "reason": None if has_key else (
                "No chart-vision model configured. Optional: the engine reads exact "
                "OHLCV bars, which is more precise than inferring candles from pixels."
            ),
            "model": _vision_model() if has_key else None,
        },
        "timeframes": frames,
        "data_sources": {
            "1h": counts["1h"],
            "1d": counts["1d"],
            "1d_wide": counts["1d_wide"],
            "daily_union": counts["daily_union"],
        },
        "thresholds": book_spec_status(),
        "engine": {
            "modules": [
                "research/vpa_bars.py",
                "research/vpa_levels.py",
                "research/vpa_score.py",
                "research/vpa_thresholds.py",
            ],
            "probability_band": [
                100 - VPA_THRESHOLDS["scoring"]["probability_ceiling"],
                VPA_THRESHOLDS["scoring"]["probability_ceiling"],
            ],
            "probability_note": (
                "VPA is directional evidence, not a calibrated forecast; probabilities are "
                "clamped to the band above."
            ),
        },
    }
