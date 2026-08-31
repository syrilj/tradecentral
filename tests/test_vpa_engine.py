"""Unit and integration tests for the Volume Price Analysis (VPA) engine.

The tests below the original block are the D1-D8 regression suite from
`docs/VPA_REBUILD_CONTRACT.md` §8. Each one fails against the pre-rebuild
engine, which returned a byte-identical analysis for every timeframe and
emitted `confidence_score: 0.86`, `probability_pct: 74/26` and
`risk_reward_ratio: "1 : 3.1"` as literals on every code path.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from research.vpa_bars import (
    TIMEFRAME_SPECS,
    bars_meta_from_series,
    load_bars,
    normalize_timeframe,
)
from research.vpa_codex import get_full_vpa_codex
from research.vpa_engine import (
    SAMPLE_CHARTS,
    analyze_chart_vpa,
    evaluate_ohlcv_series,
    generate_vpa_system_prompt,
    vpa_health,
)
from research.vpa_levels import compute_vap, detect_levels, find_pivots
from research.vpa_score import build_evidence, score_evidence
from research.vpa_thresholds import VPA_THRESHOLDS

RESEARCH = Path(__file__).resolve().parents[1] / "research"


# ---------------------------------------------------------------------------
# Original codex / sample / prompt coverage
# ---------------------------------------------------------------------------

def test_vpa_codex_structure():
    codex = get_full_vpa_codex()
    assert codex["title"] == "Volume-price rule catalog"
    assert codex["author"] == "TradeCentral"

    laws = codex["laws"]
    assert len(laws) >= 3
    law_ids = {l["id"] for l in laws}
    assert "law_supply_demand" in law_ids
    assert "law_cause_effect" in law_ids
    assert "law_effort_result" in law_ids

    principles = codex["principles"]
    assert len(principles) >= 6
    p_names = [p["name"] for p in principles]
    assert any("Relative, not absolute" in name for name in p_names)
    assert any("Reversals take time" in name for name in p_names)
    assert any("Validation or Anomaly" in name for name in p_names)

    taxonomy = codex["candle_taxonomy"]
    candle_names = {c["name"] for c in taxonomy}
    assert "Shooting Star" in candle_names
    assert "Hammer Candle" in candle_names
    assert "Long-Legged Doji" in candle_names
    assert "Hanging Man" in candle_names

    phases = [cp["phase"] for cp in codex["campaign_phases"]]
    assert "Accumulation" in phases
    assert "Buying Climax" in phases
    assert "Testing Supply (Low Volume Test)" in phases
    assert "Markup / Bull Trend" in phases
    assert "Distribution" in phases
    assert "Selling Climax" in phases


def test_sample_charts_are_not_shipped():
    assert SAMPLE_CHARTS == []


def test_published_chart_commentaries_are_not_shipped():
    res = analyze_chart_vpa(sample_id="not-a-shipped-reference")
    blob = str(res)
    assert "Coulling" not in blob
    assert "Fig 10" not in blob
    assert res.get("is_sample") is not True


def test_analyze_chart_vpa_ohlcv_and_heuristic_fallback():
    res = analyze_chart_vpa(symbol="AAPL", timeframe="1h", asset_class="equities")
    assert res["symbol"] == "AAPL"
    assert res["timeframe"] == "1h"
    assert res["engine_mode"] in {"quantitative_ohlcv_vpa", "offline_heuristic"}
    assert "primary_scenario" in res
    assert "alternative_scenarios" in res
    assert res["primary_scenario"]["probability_pct"] > 0
    assert len(res["alternative_scenarios"]) >= 1
    assert "invalidation_trigger" in res["alternative_scenarios"][0]

    res_fallback = analyze_chart_vpa(symbol="UNKNOWN_XYZ", timeframe="15m")
    assert res_fallback["symbol"] == "UNKNOWN_XYZ"
    assert res_fallback["engine_mode"] == "offline_heuristic"


def test_vpa_prompt_generation():
    prompt = generate_vpa_system_prompt()
    assert "Coulling" not in prompt
    assert "effort" in prompt.lower()
    assert "Shooting Star" in prompt
    assert "Hammer" in prompt
    assert "invalidation_trigger" in prompt


# ---------------------------------------------------------------------------
# Synthetic series builders
# ---------------------------------------------------------------------------

def _bar(date, o, h, l, c, v):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _day(i):
    return f"2026-01-{(i % 28) + 1:02d}T00:00:00"


def _bull_series(n=140, volume_mult=1.0):
    """Markup: rising price, effort on up bars, no-supply pullbacks, a test.

    `volume_mult` scales the conviction of the confirming bars so tests can
    check that stronger evidence actually produces a higher reading.
    """
    bars = []
    price = 100.0
    for i in range(n):
        if i % 10 == 4:
            # Narrow-spread low-volume down bar: no supply (bullish, Ch.5).
            o = price
            c = price - 0.15
            bars.append(_bar(_day(i), o, o + 0.05, c - 0.05, c, 300_000))
            price = c
        elif i % 10 == 8:
            # Wide up spread on heavy volume: effort matches result (Ch.2).
            o = price
            c = price + 3.2
            bars.append(_bar(_day(i), o, c + 0.1, o - 0.1, c, int(4_500_000 * volume_mult)))
            price = c
        else:
            o = price
            c = price + 0.55
            bars.append(_bar(_day(i), o, c + 0.2, o - 0.2, c, 1_000_000))
            price = c
    return bars


def _bear_series(n=140):
    """Markdown: falling price, effort on down bars, no-demand rallies."""
    bars = []
    price = 300.0
    for i in range(n):
        if i % 10 == 4:
            o = price
            c = price + 0.15
            bars.append(_bar(_day(i), o, c + 0.05, o - 0.05, c, 300_000))
            price = c
        elif i % 10 == 8:
            o = price
            c = price - 3.2
            bars.append(_bar(_day(i), o, o + 0.1, c - 0.1, c, 4_500_000))
            price = c
        else:
            o = price
            c = price - 0.55
            bars.append(_bar(_day(i), o, o + 0.2, c - 0.2, c, 1_000_000))
            price = c
    return bars


def _neutral_series(n=140):
    """Congestion: symmetric oscillation, flat volume, no anomalies."""
    bars = []
    for i in range(n):
        base = 50.0 + (1.0 if i % 2 == 0 else -1.0)
        o = base
        c = base + (0.3 if i % 2 == 0 else -0.3)
        bars.append(_bar(_day(i), o, max(o, c) + 0.2, min(o, c) - 0.2, c, 1_000_000))
    return bars


def _flat_no_test_series(n=80):
    """Perfectly constant volume, bodies filling the range: no test candle."""
    bars = []
    price = 20.0
    for i in range(n):
        o = price
        c = price + 0.10
        bars.append(_bar(_day(i), o, c, o, c, 1_000_000))
        price = c
    return bars


def _analyse(bars, timeframe="1D", symbol="SYNTH"):
    meta = bars_meta_from_series(bars, timeframe, source="synthetic")
    return evaluate_ohlcv_series(
        series=bars, symbol=symbol, timeframe=timeframe, bars_meta=meta
    )


# ---------------------------------------------------------------------------
# D1 -- the timeframe control is real
# ---------------------------------------------------------------------------

def test_d1_timeframes_return_different_bars_and_different_analysis():
    """Daily / 4h / weekly must not be byte-identical any more."""
    results = {}
    for tf in ("1D", "4h", "1W"):
        res = analyze_chart_vpa(symbol="AAPL", timeframe=tf)
        assert res["bars_meta"]["available"] is True, f"{tf} loaded no bars"
        results[tf] = res

    counts = {tf: r["bars_meta"]["bar_count"] for tf, r in results.items()}
    assert len(set(counts.values())) == 3, f"bar counts collapsed: {counts}"

    served = {tf: r["bars_meta"]["timeframe_served"] for tf, r in results.items()}
    assert served == {"1D": "1D", "4h": "4h", "1W": "1W"}

    # Different bars must produce a different read, not the same canned one.
    signatures = {
        tf: (
            r["confidence_score"],
            r["primary_scenario"]["probability_pct"],
            r["forensic_breakdown"]["support_resistance"]["floor_support"],
            (r["vap"] or {}).get("poc"),
        )
        for tf, r in results.items()
    }
    assert len(set(signatures.values())) == 3, f"analyses collapsed: {signatures}"


def test_d1_sub_hourly_is_downgraded_not_faked():
    """There is no data below 1h; 15m must say so rather than serve daily."""
    for tf in ("1m", "5m", "15m", "30m"):
        bars, meta = load_bars("AAPL", tf)
        assert meta["timeframe_requested"] == tf
        assert meta["downgraded"] is True
        assert meta["timeframe_served"] == "1h"
        assert "no data below 1h" in meta["downgrade_reason"]
        assert len(bars) == meta["bar_count"] > 0


def test_d1_downgrade_lowers_confidence():
    """A timeframe we could not honour must not be as trustworthy as one we could."""
    honest = analyze_chart_vpa(symbol="AAPL", timeframe="1h")
    downgraded = analyze_chart_vpa(symbol="AAPL", timeframe="15m")
    assert downgraded["bars_meta"]["downgraded"] is True
    assert honest["bars_meta"]["downgraded"] is False
    # Same served bars, so the only difference is the penalty.
    assert downgraded["confidence_score"] < honest["confidence_score"]


def test_d1_symbol_without_hourly_data_falls_back_to_daily_with_reason():
    """Hardcoding a symbol here is a trap: intraday coverage grows as the
    backfill runs, so yesterday's daily-only ticker silently becomes an hourly
    one and the test starts asserting nothing. Pick one at runtime instead."""
    import glob
    import os

    from research.vpa_bars import DAILY_DIRS, HOURLY_DIR

    hourly = {os.path.basename(p)[: -len(".parquet")] for p in glob.glob(f"{HOURLY_DIR}/*.parquet")}
    daily = set()
    for root in DAILY_DIRS:
        daily |= {os.path.basename(p).split(".")[0] for p in glob.glob(f"{root}/*.parquet")}

    candidates = sorted(daily - hourly)
    if not candidates:
        pytest.skip("every symbol on disk now has hourly bars; nothing to downgrade")

    bars, meta = load_bars(candidates[0], "1h")
    assert meta["timeframe_served"] == "1D"
    assert meta["downgraded"] is True
    assert "no hourly bars" in meta["downgrade_reason"]
    assert bars


def test_timeframe_alias_normalisation():
    assert normalize_timeframe("Daily") == "1D"
    assert normalize_timeframe("weekly") == "1W"
    assert normalize_timeframe("60m") == "1h"
    assert normalize_timeframe("15-Minute") == "15m"
    assert normalize_timeframe(None) == "1D"


# ---------------------------------------------------------------------------
# D4 -- probabilities, confidence and R:R are derived
# ---------------------------------------------------------------------------

def test_d4_three_series_three_different_reads():
    bull = _analyse(_bull_series())
    bear = _analyse(_bear_series())
    neutral = _analyse(_neutral_series())

    assert bull["primary_scenario"]["direction"] == "BULLISH"
    assert bear["primary_scenario"]["direction"] == "BEARISH"

    probs = [r["primary_scenario"]["probability_pct"] for r in (bull, bear, neutral)]
    confs = [r["confidence_score"] for r in (bull, bear, neutral)]
    assert len(set(probs)) >= 2, f"probabilities collapsed: {probs}"
    # The bull and bear fixtures are deliberate mirror images, so identical
    # confidence for those two is correct -- confidence measures how much the
    # data supports *a* read, not which way it points. The congestion series
    # must be clearly less confident than both.
    assert len(set(confs)) >= 2, f"confidences collapsed: {confs}"
    assert confs[2] < confs[0] and confs[2] < confs[1], f"congestion not discounted: {confs}"

    for res in (bull, bear, neutral):
        # The old constants must not come back out of a derived pipeline.
        assert not (
            res["confidence_score"] == 0.86
            and res["primary_scenario"]["probability_pct"] == 74
        )
        rr = res["trade_execution_guide"]["risk_reward_ratio"]
        assert rr is None or isinstance(rr, float), f"R:R must be numeric or null, got {rr!r}"
        assert rr != "1 : 3.1"


def test_d4_probability_is_bounded_to_the_declared_band():
    # The primary read is max(p, 1-p) and so can never fall below 50; the band
    # is [50, ceiling] and the alternative takes the complement.
    for series in (_bull_series(), _bear_series(), _neutral_series()):
        res = _analyse(series)
        basis = res["probability_basis"]
        lo, hi = basis["band"]
        assert [lo, hi] == [50, 80]
        assert basis["alternative_band"] == [20, 50]
        pct = res["primary_scenario"]["probability_pct"]
        assert lo <= pct <= hi
        assert "not a calibrated forecast" in basis["note"]


def test_d4_distinct_evidence_profiles_give_distinct_readings():
    """A hard clamp collapsed every strongly-directional read onto one number,
    throwing away the ordering the evidence ledger had just computed.

    Note volume is graded in tiers, not continuously -- reads "high"
    and "ultra high", so past the ultra-high threshold extra volume adds no
    further weight. Conviction therefore has to vary by evidence *profile*.
    """
    seen = set()
    for series in (_bull_series(), _bear_series(), _neutral_series(),
                   _bull_series(n=60), _bear_series(n=60)):
        res = _analyse(series)
        pct = res["primary_scenario"]["probability_pct"]
        assert 50 <= pct < 80, f"reading {pct} outside the usable band"
        seen.add(pct)
    assert len(seen) > 1, "different evidence profiles produced one flat number"


def test_d4_scenarios_complete_to_one_hundred():
    for series in (_bull_series(), _bear_series(), _neutral_series()):
        res = _analyse(series)
        total = res["primary_scenario"]["probability_pct"] + sum(
            alt["probability_pct"] for alt in res["alternative_scenarios"]
        )
        assert total == 100


def test_d4_confidence_responds_to_bar_count():
    """Fewer bars, less coverage, lower confidence -- all else equal."""
    long_series = _bull_series(200)
    short_series = long_series[-40:]
    assert _analyse(short_series)["confidence_score"] < _analyse(long_series)["confidence_score"]


def test_d4_evidence_ledger_backs_every_number():
    res = _analyse(_bull_series())
    evidence = res["evidence"]
    assert evidence, "no evidence emitted"
    for item in evidence:
        assert set(item) >= {"signal", "direction", "weight", "bars", "book_ref", "detail"}
        assert item["direction"] in {"bullish", "bearish"}
        assert item["weight"] > 0
        # Contract §1.3: if a rule cannot be cited, the rule does not ship.
        assert item["book_ref"].startswith("rule.")
    basis = res["probability_basis"]
    assert basis["bull_score"] > 0
    assert basis["evidence_count"] == len(evidence)


def test_d4_no_old_constants_as_literals_in_derived_modules():
    """Hard regression guard from contract §5.

    `vpa_engine.py` is only scanned past the sample library, because
    SAMPLE_CHARTS legitimately contains own published figures.
    """
    engine_src = (RESEARCH / "vpa_engine.py").read_text()
    engine_src = engine_src[engine_src.index("def generate_vpa_system_prompt"):]
    sources = {"vpa_engine.py": engine_src}
    for name in ("vpa_score.py", "vpa_levels.py", "vpa_bars.py", "vpa_thresholds.py"):
        sources[name] = (RESEARCH / name).read_text()

    for name, src in sources.items():
        assert "1 : 3.1" not in src, f"{name} still emits the canned R:R string"
        assert not re.search(r"(?<![\d.])0\.86(?![\d])", src), f"{name} contains a 0.86 literal"
        assert not re.search(
            r"probability_pct[\"']?\s*[:=]\s*(74|26)\b", src
        ), f"{name} contains a hardcoded probability"


# ---------------------------------------------------------------------------
# D5 -- real support / resistance
# ---------------------------------------------------------------------------

def test_d5_planted_pivots_are_detected_and_clustered():
    """Three touches of a 110 ceiling and a 100 floor must become two zones."""
    bars = []
    i = 0
    for _ in range(4):
        for price in (100.0, 103.0, 107.0, 110.0, 107.0, 103.0, 100.0):
            hi = price + 0.2
            lo = price - 0.2
            bars.append(_bar(_day(i), price, hi, lo, price, 1_000_000))
            i += 1
    # Land well inside the range so both bands are "actionable".
    bars.append(_bar(_day(i), 105.0, 105.2, 104.8, 105.0, 1_000_000))

    pivots = find_pivots(bars)
    assert pivots["highs"], "no pivot highs found in a series with four clear peaks"
    assert pivots["lows"], "no pivot lows found in a series with four clear troughs"

    result = detect_levels(bars)
    prices = [lvl["price"] for lvl in result["levels"]]
    assert any(abs(p - 110.0) < 1.0 for p in prices), f"ceiling missed: {prices}"
    assert any(abs(p - 100.0) < 1.0 for p in prices), f"floor missed: {prices}"

    ceiling = min(
        (lvl for lvl in result["levels"] if abs(lvl["price"] - 110.0) < 1.0),
        key=lambda z: abs(z["price"] - 110.0),
    )
    assert ceiling["touches"] >= 2
    assert ceiling["source"] == "pivot_cluster"
    assert 0.0 <= ceiling["strength"] <= 1.0
    assert isinstance(ceiling["role_reversed"], bool)


def test_d5_levels_are_numeric_and_drawable():
    res = _analyse(_bull_series())
    assert isinstance(res["levels"], list)
    for lvl in res["levels"]:
        assert set(lvl) >= {
            "price", "low", "high", "kind", "strength", "touches",
            "source", "role_reversed", "last_touch_bar",
        }
        assert lvl["low"] <= lvl["price"] <= lvl["high"]
        assert lvl["kind"] in {"support", "resistance"}


def test_d5_role_reversal_needs_a_volume_backed_break():
    """Ch.7: a ceiling closed through on *rising* volume becomes a floor."""
    bars = []
    i = 0
    for _ in range(4):
        for price in (100.0, 104.0, 108.0, 104.0, 100.0):
            bars.append(_bar(_day(i), price, price + 0.3, price - 0.3, price, 1_000_000))
            i += 1
    # Clear-water close above the 108 ceiling on 4x volume.
    bars.append(_bar(_day(i), 108.0, 116.0, 107.8, 115.5, 4_000_000))
    i += 1
    for _ in range(3):
        bars.append(_bar(_day(i), 115.5, 116.0, 115.0, 115.5, 1_100_000))
        i += 1

    result = detect_levels(bars)
    reversed_zones = [lvl for lvl in result["levels"] if lvl["role_reversed"]]
    assert reversed_zones, f"no role reversal detected: {[l['price'] for l in result['levels']]}"
    assert all(z["kind"] == "support" for z in reversed_zones)

    evidence = build_evidence(bars, result)
    signals = {e["signal"] for e in evidence}
    assert "breakout_confirmed" in signals
    assert "role_reversal" in signals


def test_d5_low_volume_breakout_is_a_fakeout_not_strength():
    """Ch.7: clear water without volume is the book's trap, and must be signed
    against the breakout rather than reported as bullish."""
    bars = []
    i = 0
    for _ in range(4):
        for price in (100.0, 104.0, 108.0, 104.0, 100.0):
            bars.append(_bar(_day(i), price, price + 0.3, price - 0.3, price, 1_000_000))
            i += 1
    bars.append(_bar(_day(i), 108.0, 116.0, 107.8, 115.5, 400_000))  # 0.4x volume

    result = detect_levels(bars)
    evidence = build_evidence(bars, result)
    fakeouts = [e for e in evidence if e["signal"] == "fakeout_risk"]
    assert fakeouts, f"low-volume breakout not flagged: {[e['signal'] for e in evidence]}"
    assert fakeouts[0]["direction"] == "bearish"
    assert not any(e["signal"] == "breakout_confirmed" for e in evidence)


# ---------------------------------------------------------------------------
# D6 -- volume at price distributed across each bar's range
# ---------------------------------------------------------------------------

def test_d6_vap_distributes_volume_across_the_bar_range():
    """The discriminating case: one huge bar spanning the whole range and
    closing at the top, versus many small bars parked at 95.

    Close-binning (the old code) credits the whole 40M to the bin holding 110
    and puts the POC at the top of the range. Range distribution spreads it over
    twenty bins and the real volume shelf at 95 wins.
    """
    bars = [_bar(_day(0), 90.0, 110.0, 90.0, 110.0, 40_000_000)]
    for i in range(1, 40):
        bars.append(_bar(_day(i), 95.0, 95.6, 94.6, 95.2, 3_000_000))

    vap = compute_vap(bars)
    assert vap is not None
    assert vap["method"] == "range_distributed"
    assert abs(vap["poc"] - 95.0) < 1.5, f"POC landed at {vap['poc']}, expected the 95 shelf"
    assert vap["poc"] < 100.0, "POC still tracks the close, not the traded range"
    assert vap["value_area_low"] <= vap["poc"] <= vap["value_area_high"]
    assert 0.65 <= vap["value_area_pct"] <= 1.0
    assert sum(b["volume"] for b in vap["bins"]) == pytest.approx(vap["total_volume"], rel=1e-6)


def test_d6_known_volume_node_is_found_within_tolerance():
    """Volume planted in a narrow band must surface as the POC."""
    bars = []
    for i in range(60):
        if 20 <= i < 30:
            bars.append(_bar(_day(i), 50.0, 50.4, 49.6, 50.1, 9_000_000))  # the node
        else:
            bars.append(_bar(_day(i), 55.0 + i * 0.1, 56.0 + i * 0.1, 54.0 + i * 0.1,
                             55.5 + i * 0.1, 500_000))
    vap = compute_vap(bars)
    assert abs(vap["poc"] - 50.0) < 1.0, f"planted node missed, POC={vap['poc']}"


# ---------------------------------------------------------------------------
# D7 -- detections reflect detection
# ---------------------------------------------------------------------------

def test_d7_no_test_candle_reports_false():
    res = _analyse(_flat_no_test_series())
    tests = res["forensic_breakdown"]["test_candles"]
    assert tests["detected"] is False
    assert tests["type"] == "None"
    assert tests["result"] == "None"
    stopping = res["forensic_breakdown"]["stopping_or_topping"]
    assert stopping["detected"] is False
    assert stopping["type"] == "None"


def test_d7_real_test_candle_reports_true_with_bars():
    bars = _flat_no_test_series(60)
    last = bars[-1]
    # A narrow-bodied probe with a deep lower wick on 1/10th of the volume:
    # low volume test of supply (Ch.6).
    bars.append(_bar(_day(61), last["close"], last["close"] + 0.05,
                     last["close"] - 1.5, last["close"] + 0.02, 100_000))
    res = _analyse(bars)
    tests = res["forensic_breakdown"]["test_candles"]
    assert tests["detected"] is True
    assert tests["bars"], "a detection must name the bars it came from"
    assert tests["book_ref"].startswith("rule.")


def test_d7_no_data_path_invents_nothing():
    """The old fallback returned a full analysis for a symbol it never loaded."""
    res = analyze_chart_vpa(symbol="UNKNOWN_XYZ", timeframe="15m")
    assert res["engine_mode"] == "offline_heuristic"
    assert res["confidence_score"] is None
    assert res["primary_scenario"]["probability_pct"] is None
    assert res["trade_execution_guide"]["risk_reward_ratio"] is None
    assert res["forensic_breakdown"]["test_candles"]["detected"] is False
    assert res["forensic_breakdown"]["stopping_or_topping"]["detected"] is False
    assert res["evidence"] == []
    assert res["levels"] == []
    assert res["data_status"]["analysed"] is False


# ---------------------------------------------------------------------------
# D2 / D3 -- snapshot and vision honesty
# ---------------------------------------------------------------------------

def test_d3_vision_status_reports_missing_credentials(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("EDGE_VPA_DISABLE_VERTEX", "1")
    res = analyze_chart_vpa(symbol="AAPL", timeframe="1D", image_base64="ZmFrZQ==")
    status = res["vision_status"]
    assert status["available"] is False
    assert status["image_received"] is True
    assert status["image_used"] is False
    # Vision is an optional enrichment, never a prerequisite: the response must
    # say so rather than presenting a missing key as a broken feature.
    assert status["required"] is False
    assert status["primary_path"] == "quantitative_ohlcv_vpa"
    assert status["reason"], "an unused image must always come with an explanation"
    # The bars still get analysed -- we just do not pretend the image did anything.
    assert res["engine_mode"] == "quantitative_ohlcv_vpa"


def test_vision_is_never_required_for_a_symbol_we_hold_bars_for(monkeypatch):
    """The screenshot path must not be a dead end when no model is configured."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("EDGE_VPA_DISABLE_VERTEX", "1")
    res = analyze_chart_vpa(symbol="AAPL", timeframe="1D", image_base64="ZmFrZQ==")
    assert res["primary_scenario"]["probability_pct"] is not None
    assert res["levels"], "a full forensic read must still be produced"
    assert res["evidence"], "evidence ledger must be populated without vision"


def test_health_availability_is_per_symbol(monkeypatch):
    """A symbol with no hourly parquet must not be offered 1h in the dropdown."""
    from research.vpa_engine import vpa_health

    globally = {t["value"]: t["available"] for t in vpa_health()["timeframes"]}
    assert globally["1h"] is True, "fixture expects some hourly coverage on disk"

    scoped = {t["value"]: t for t in vpa_health("ZZZZNOTREAL")["timeframes"]}
    assert scoped["1h"]["available"] is False
    assert scoped["1D"]["available"] is False
    assert "ZZZZNOTREAL" in scoped["1h"]["reason"]


def test_d2_image_wins_precedence_over_bars_when_vision_is_available(monkeypatch):
    """The old entrypoint checked `ohlcv_series` first, so the UI's snapshot was
    silently discarded on every request."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_vision = {
        "symbol": "AAPL",
        "primary_scenario": {"direction": "BULLISH", "rationale": "Vision read."},
    }
    with patch("research.vpa_engine.call_gemini_vision", return_value=fake_vision) as call:
        res = analyze_chart_vpa(symbol="AAPL", timeframe="1D", image_base64="ZmFrZQ==")
    assert call.called, "image present and vision available, but vision never ran"
    assert res["engine_mode"] == "vision+quant"
    assert res["vision_status"]["image_used"] is True
    assert res["vision_read"] == fake_vision
    assert any(e["signal"] == "vision_agreement" for e in res["evidence"])


def test_d2_image_only_request_uses_vision_alone(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_vision = {"symbol": "CHART", "primary_scenario": {"direction": "BEARISH"}}
    with patch("research.vpa_engine.call_gemini_vision", return_value=fake_vision):
        res = analyze_chart_vpa(image_base64="ZmFrZQ==")
    assert res["engine_mode"] == "vision_multimodal"
    assert res["vision_status"]["image_used"] is True


def test_d2_vision_failure_falls_back_and_says_why(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with patch("research.vpa_engine.call_gemini_vision", side_effect=RuntimeError("boom")):
        res = analyze_chart_vpa(symbol="AAPL", timeframe="1D", image_base64="ZmFrZQ==")
    assert res["vision_status"]["image_used"] is False
    assert "boom" in res["vision_status"]["reason"]
    assert res["engine_mode"] == "quantitative_ohlcv_vpa"


# ---------------------------------------------------------------------------
# Health endpoint + contract shape
# ---------------------------------------------------------------------------

def test_vpa_health_shape():
    health = vpa_health()
    assert set(health) >= {"vision", "timeframes", "data_sources"}
    assert set(health["vision"]) >= {"available", "reason"}

    values = {tf["value"] for tf in health["timeframes"]}
    assert values == {spec["value"] for spec in TIMEFRAME_SPECS}

    by_value = {tf["value"]: tf for tf in health["timeframes"]}
    for unavailable in ("1m", "5m", "15m", "30m"):
        assert by_value[unavailable]["available"] is False
        assert by_value[unavailable]["reason"]
    for available in ("1h", "2h", "4h", "1D", "1W"):
        assert by_value[available]["available"] is True
        assert by_value[available]["symbols"] > 0

    assert health["data_sources"]["1h"] > 0
    assert health["data_sources"]["daily_union"] > health["data_sources"]["1h"]


def test_contract_response_shape():
    """Every §4 field present with the right type on a real quantitative read."""
    res = analyze_chart_vpa(symbol="AAPL", timeframe="1D")

    assert isinstance(res["confidence_score"], float)
    assert isinstance(res["primary_scenario"]["probability_pct"], int)
    assert isinstance(res["alternative_scenarios"][0]["probability_pct"], int)

    meta = res["bars_meta"]
    assert set(meta) >= {
        "timeframe_requested", "timeframe_served", "downgraded", "downgrade_reason",
        "bar_count", "first_bar", "last_bar", "source",
    }
    assert isinstance(meta["bar_count"], int)
    assert isinstance(meta["downgraded"], bool)

    assert isinstance(res["levels"], list)
    vap = res["vap"]
    assert set(vap) >= {"poc", "value_area_low", "value_area_high", "bins"}
    assert isinstance(vap["bins"], list) and vap["bins"]
    assert set(vap["bins"][0]) >= {"low", "high", "volume"}

    basis = res["probability_basis"]
    assert set(basis) >= {"bull_score", "bear_score", "method", "band", "note"}

    status = res["vision_status"]
    assert set(status) >= {"available", "reason", "image_received", "image_used"}

    assert res["engine_mode"] in {
        "quantitative_ohlcv_vpa", "vision_multimodal", "vision+quant",
        "canonical_codex_reference", "offline_heuristic",
    }

    rr = res["trade_execution_guide"]["risk_reward_ratio"]
    assert rr is None or isinstance(rr, float)


def test_score_evidence_is_pure_and_deterministic():
    bars = _bull_series()
    levels = detect_levels(bars)
    first = score_evidence(bars, levels)
    second = score_evidence(bars, levels)
    assert first["primary_probability_pct"] == second["primary_probability_pct"]
    assert first["confidence"]["confidence_score"] == second["confidence"]["confidence_score"]


# ---------------------------------------------------------------------------
# Ch.8 / Ch.11 -- structures the engine previously could not see at all
# ---------------------------------------------------------------------------

def _zigzag(points, per=7):
    """Bars tracing straight legs between successive turning points."""
    bars = []
    for a, b in zip(points, points[1:]):
        for k in range(per):
            p = a + (b - a) * k / per
            nxt = a + (b - a) * (k + 1) / per
            bars.append({
                "date": f"d{len(bars)}", "open": p,
                "high": max(p, nxt) + 0.05, "low": min(p, nxt) - 0.05,
                "close": nxt, "volume": 1_000_000,
            })
    return bars


@pytest.mark.parametrize(
    "name,points",
    [
        # A triple top needs lows that are NOT rising -- rising lows under a
        # flat ceiling is a rising triangle by definition, not a triple top.
        ("Triple Top", [100, 110, 99, 110, 98, 110, 95]),
        ("Triple Bottom", [110, 100, 111, 100, 112, 100, 115]),
        ("Rising Triangle", [96, 110, 99, 110, 103, 110, 106]),
        ("Falling Triangle", [118, 100, 114, 100, 110, 100, 104]),
        ("Pennant", [90, 116, 96, 112, 100, 108, 103]),
    ],
)
def test_ch11_congestion_patterns_are_detected(name, points):
    """Congestion patterns measured from pivot geometry."""
    from research.vpa_levels import detect_congestion_patterns

    found = detect_congestion_patterns(_zigzag(points))
    names = [p["pattern"] for p in found]
    assert name in names, f"expected {name}, got {names}"
    for p in found:
        assert p["book_ref"].startswith("rule."), "every pattern must cite the book"
        assert p["direction"] in ("bullish", "bearish")


def test_ch11_triangle_suppresses_the_duplicate_triple():
    """A rising triangle also has a ceiling tested three times; reporting
    'Triple Top' alongside it would double-count one shelf and hand the scorer
    two opposite directions for the same structure."""
    from research.vpa_levels import detect_congestion_patterns

    names = [p["pattern"] for p in detect_congestion_patterns(
        _zigzag([96, 110, 99, 110, 103, 110, 106]))]
    assert "Rising Triangle" in names
    assert "Triple Top" not in names


def test_ch8_dynamic_trend_follows_the_pivots():
    from research.vpa_levels import detect_dynamic_trend

    up = detect_dynamic_trend(_zigzag([90, 100, 95, 108, 102, 116, 110]))
    assert up and up["direction"] == "bullish"
    assert up["book_ref"].startswith("rule.")

    down = detect_dynamic_trend(_zigzag([116, 106, 112, 98, 104, 90, 96]))
    assert down and down["direction"] == "bearish"


def test_ch8_and_ch11_reach_the_api_response():
    res = analyze_chart_vpa(symbol="NVDA", timeframe="1D")
    assert "dynamic_trend" in res
    assert "congestion_patterns" in res
    assert isinstance(res["congestion_patterns"], list)


# ---------------------------------------------------------------------------
# Walk-forward harness -- the property the IS/OOS result depends on
# ---------------------------------------------------------------------------

def test_backtest_reads_cannot_see_the_future():
    """If a read at `t` changed when bars after `t` changed, every hit rate in
    docs/VPA_VALIDATION.md would be meaningless. Mutate the future violently and
    assert the read is byte-identical."""
    from research.vpa_backtest import _forward_return

    bars = _bull_series(n=200)
    t = 150

    before = analyze_chart_vpa(symbol="LOOKAHEAD", timeframe="1D", ohlcv_series=bars[:t])

    tampered = [dict(b) for b in bars]
    for i in range(t, len(tampered)):
        tampered[i]["close"] *= 3.0
        tampered[i]["high"] *= 3.0
        tampered[i]["low"] *= 3.0
        tampered[i]["volume"] *= 50

    after = analyze_chart_vpa(symbol="LOOKAHEAD", timeframe="1D", ohlcv_series=tampered[:t])

    assert before["primary_scenario"] == after["primary_scenario"]
    assert before["confidence_score"] == after["confidence_score"]
    assert before["levels"] == after["levels"]

    # And the forward return must read strictly beyond the as-of bar.
    assert _forward_return(bars, t, 10) != _forward_return(tampered, t, 10)


def test_backtest_benchmark_is_the_base_rate_not_a_coin_flip():
    """Equities drift up, so scoring against 50% credits the engine for the
    market rising. The first version of the harness did exactly that and
    reported a 'signal' that was pure drift."""
    from research.vpa_backtest import _summarise

    # Every window positive: a skill-free bullish caller scores 100%.
    rows = [
        {"direction": "BULLISH", "probability_pct": 60, "forward_return": 0.01, "as_of": f"d{i}"}
        for i in range(200)
    ]
    s = _summarise(rows, "drift")
    assert s["base_rate_up"] == 1.0
    assert s["expected_hit_rate_no_skill"] == 1.0
    # Hit rate 100% but zero edge, because no skill was required to get there.
    assert s["hit_rate"] == 1.0
    assert s["hit_rate"] - s["expected_hit_rate_no_skill"] == 0.0


# ---------------------------------------------------------------------------
# D5b -- zones must not duplicate, and one break is one piece of evidence
# ---------------------------------------------------------------------------

def _real_bars(symbol="IONQ", timeframe="1D"):
    from research.vpa_bars import load_bars
    bars, meta = load_bars(symbol, timeframe)
    if len(bars) < 60:
        import pytest
        pytest.skip(f"no bars on disk for {symbol} {timeframe}")
    return bars, meta


def _overlap_fraction(a, b):
    inter = max(0.0, min(a["high"], b["high"]) - max(a["low"], b["low"]))
    narrower = min(a["high"] - a["low"], b["high"] - b["low"])
    return (inter / narrower) if narrower > 0 else 0.0


def test_d5_zones_do_not_overlap_each_other():
    """A support-origin cluster and a resistance-origin cluster at the same
    price are one level, not two. Unmerged bands double-count every break
    through them."""
    bars, _ = _real_bars()
    levels = detect_levels(bars)["levels"]
    dupes = [
        (a["price"], b["price"], round(_overlap_fraction(a, b), 3))
        for i, a in enumerate(levels)
        for b in levels[i + 1:]
        if _overlap_fraction(a, b) > 0.5
    ]
    assert not dupes, f"overlapping duplicate zones survived clustering: {dupes}"


def test_d5_one_bar_break_is_one_breakout_event():
    """One bar crossing N bands is one market event, not N."""
    bars, _ = _real_bars()
    breakouts = detect_levels(bars)["breakouts"]
    bar_ids = [b["bar"] for b in breakouts]
    assert len(bar_ids) == len(set(bar_ids)), (
        f"the same bar reported as several independent breakouts: {sorted(bar_ids)}"
    )


def test_d5_evidence_ledger_has_no_duplicate_rows():
    """Two identical rows with identical weight are one signal counted twice."""
    bars, meta = _real_bars()
    levels = detect_levels(bars)
    evidence = score_evidence(bars, levels, meta)["evidence"]
    keys = [(e["signal"], e["direction"], tuple(e.get("bars") or ())) for e in evidence]
    dupes = [k for k in set(keys) if keys.count(k) > 1]
    assert not dupes, f"evidence ledger double-counts: {dupes}"


def test_d5_no_single_signal_dominates_the_ledger():
    """A ledger that is mostly one signal type is a detector misfiring, not a
    read. No signal may be more than half the rows."""
    bars, meta = _real_bars()
    levels = detect_levels(bars)
    evidence = score_evidence(bars, levels, meta)["evidence"]
    from collections import Counter
    counts = Counter(e["signal"] for e in evidence)
    signal, n = counts.most_common(1)[0]
    assert n <= len(evidence) / 2, (
        f"{signal} is {n} of {len(evidence)} ledger rows: {dict(counts)}"
    )


def test_d5_stale_breaks_are_not_live_evidence():
    """A band broken long ago and left far behind is history, not a signal."""
    bars, _ = _real_bars()
    res = detect_levels(bars)
    n = len(bars)
    atr = res["atr"]
    last = res["last_close"]
    stale = [
        (b["price"], n - 1 - b["bar"], round(abs(b["price"] - last) / atr, 2))
        for b in res["breakouts"]
        if (n - 1 - b["bar"]) > 30 or abs(b["price"] - last) / max(atr, 1e-9) > 3.0
    ]
    assert not stale, f"stale/distant breaks reported as live (price, age, atr_away): {stale}"


def test_d5_fakeout_rationale_states_which_way_price_broke():
    """'Closed outside the band' does not say whether that was a failed rally
    or a failed breakdown -- the two mean opposite things."""
    bars, meta = _real_bars()
    levels = detect_levels(bars)
    evidence = score_evidence(bars, levels, meta)["evidence"]
    fakeouts = [e for e in evidence if e["signal"] == "fakeout_risk"]
    if not fakeouts:
        import pytest
        pytest.skip("no fakeout in this window")
    for e in fakeouts:
        text = e["detail"].lower()
        assert ("above" in text or "below" in text), (
            f"fakeout rationale omits direction: {e['detail']}"
        )


def test_d5_market_phase_agrees_with_the_window_the_read_uses():
    """Ch.2: phase is read from volume behaviour over the window being scanned.
    Calling a 20-bar bullish read 'Accumulation (lower half)' because a spike
    60 bars back sits above price is a window mismatch, not a Wyckoff phase."""
    from research.vpa_engine import evaluate_ohlcv_series
    bars, meta = _real_bars()
    res = evaluate_ohlcv_series(bars, "IONQ", "1D", bars_meta=meta)
    phase = res["market_phase"]
    direction = res["dominant_sentiment"]
    scan = int(VPA_THRESHOLDS["signals"]["scan_window"])
    window = bars[-scan:]
    hi = max(b["high"] for b in window)
    lo = min(b["low"] for b in window)
    pos = (bars[-1]["close"] - lo) / (hi - lo) if hi > lo else 0.5
    if "Bullish" in direction and pos > 0.6:
        assert "Accumulation" not in phase, (
            f"phase {phase!r} says lower-half but price sits at {pos:.2f} of the "
            f"{scan}-bar range with a {direction} read"
        )


def test_normalize_series_reverses_descending_order():
    """External APIs returning newest-first series must be reversed to chronological ascending."""
    from research.vpa_engine import _normalize_series
    descending = [
        {"date": "2026-09-03", "open": 102.0, "high": 105.0, "low": 101.5, "close": 104.0, "volume": 1_000_000},
        {"date": "2026-09-02", "open": 100.5, "high": 102.5, "low": 100.0, "close": 102.0, "volume": 800_000},
        {"date": "2026-09-01", "open": 98.0, "high": 101.0, "low": 97.5, "close": 100.5, "volume": 900_000},
    ]
    ascending = _normalize_series(descending)
    assert len(ascending) == 3
    assert ascending[0]["date"] == "2026-09-01"
    assert ascending[1]["date"] == "2026-09-02"
    assert ascending[2]["date"] == "2026-09-03"

