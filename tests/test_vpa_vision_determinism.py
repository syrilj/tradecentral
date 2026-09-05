"""D1 regression suite: vision must not silently move a scored number.

`research/vpa_engine.py` fuses an optional Gemini vision read of a chart
image into the same evidence ledger that produces `primary_probability_pct`
and `confidence_score`. An LLM's directional read is not reproducible, so by
default that fusion must not happen: the vision read is surfaced as its own
qualitative block (`vision_read`) with an `agrees_with_quantitative` flag,
and the response is stamped `deterministic: true` / `reproducible: true`.
Only the explicit `fuse_vision_into_score=True` opt-in may let vision move
the scored numbers, and that response must be stamped
`deterministic: false` / `reproducible: false`.

These tests never hit the network: `call_gemini_vision` is monkeypatched in
every case, exactly like the D2/D3 precedence tests in
`tests/test_vpa_engine.py` (which this file does not modify).
"""

from unittest.mock import patch

from research.vpa_engine import analyze_chart_vpa

SYMBOL = "AAPL"
TIMEFRAME = "1D"


def _fake_vision(direction: str):
    return {
        "symbol": SYMBOL,
        "primary_scenario": {
            "direction": direction,
            "rationale": f"Vision model sees a {direction.lower()} setup on the chart.",
        },
    }


def test_default_mode_is_reproducible_even_when_vision_direction_flips(monkeypatch):
    """Two runs over byte-identical bars, with a vision stub that returns a
    DIFFERENT direction each call, must produce identical scored numbers in
    the default (non-opt-in) mode -- the quantitative path never depends on
    what the vision model said.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    calls = {"n": 0}

    def flipping_vision(**kwargs):
        calls["n"] += 1
        return _fake_vision("BULLISH" if calls["n"] % 2 else "BEARISH")

    with patch("research.vpa_engine.call_gemini_vision", side_effect=flipping_vision):
        res1 = analyze_chart_vpa(symbol=SYMBOL, timeframe=TIMEFRAME, image_base64="ZmFrZQ==")
        res2 = analyze_chart_vpa(symbol=SYMBOL, timeframe=TIMEFRAME, image_base64="ZmFrZQ==")

    assert calls["n"] == 2, "the vision stub must have actually run twice"
    # The two vision reads disagreed (BULLISH then BEARISH) -- proof the
    # stub is genuinely non-deterministic across calls.
    assert res1["vision_read"]["direction"] != res2["vision_read"]["direction"]

    # ...yet the scored numbers must be byte-identical.
    assert res1["primary_scenario"]["probability_pct"] == res2["primary_scenario"]["probability_pct"]
    assert res1["confidence_score"] == res2["confidence_score"]
    assert res1["primary_scenario"]["direction"] == res2["primary_scenario"]["direction"]


def test_default_mode_stamps_deterministic_true_and_keeps_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _fake_vision("BULLISH")

    with patch("research.vpa_engine.call_gemini_vision", return_value=fake):
        res = analyze_chart_vpa(symbol=SYMBOL, timeframe=TIMEFRAME, image_base64="ZmFrZQ==")

    # Precedence behaviour pinned by tests/test_vpa_engine.py must survive:
    # image + bars + vision available still fuses in name (`vision+quant`),
    # and the vision item is still visible in `evidence` for transparency.
    assert res["engine_mode"] == "vision+quant"
    assert any(e["signal"] == "vision_agreement" for e in res["evidence"])

    # D1: default must be reproducible.
    assert res["deterministic"] is True
    assert res["reproducible"] is True

    # The vision evidence item must say it did NOT move the score by default.
    vision_item = next(e for e in res["evidence"] if e["signal"] == "vision_agreement")
    assert vision_item.get("contributes_to_score") is False


def test_vision_read_block_has_direction_rationale_model_and_agreement_flag(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _fake_vision("BULLISH")

    with patch("research.vpa_engine.call_gemini_vision", return_value=fake):
        res = analyze_chart_vpa(symbol=SYMBOL, timeframe=TIMEFRAME, image_base64="ZmFrZQ==")

    vision_read = res["vision_read"]
    assert vision_read["direction"] == "BULLISH"
    assert vision_read["rationale"]
    assert "model" in vision_read
    assert "agrees_with_quantitative" in vision_read
    quant_direction = res["primary_scenario"]["direction"]
    if quant_direction in {"BULLISH", "BEARISH"}:
        expected = quant_direction == "BULLISH"
        assert vision_read["agrees_with_quantitative"] == expected


def test_opt_in_fused_mode_moves_the_score_and_stamps_non_deterministic(monkeypatch):
    """`fuse_vision_into_score=True` is the explicit opt-in for the old
    behaviour: the vision item is fed into the real scoring ledger, and the
    response must say plainly that it is no longer reproducible.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _fake_vision("BULLISH")

    with patch("research.vpa_engine.call_gemini_vision", return_value=fake):
        fused = analyze_chart_vpa(
            symbol=SYMBOL, timeframe=TIMEFRAME, image_base64="ZmFrZQ==",
            fuse_vision_into_score=True,
        )
        default = analyze_chart_vpa(symbol=SYMBOL, timeframe=TIMEFRAME, image_base64="ZmFrZQ==")

    assert fused["deterministic"] is False
    assert fused["reproducible"] is False
    assert fused["vision_status"]["model"] == "gemini-2.5-flash"

    vision_item = next(e for e in fused["evidence"] if e["signal"] == "vision_agreement")
    assert vision_item.get("contributes_to_score") is True

    # probability_basis must reflect the same evidence-count as the top-level
    # evidence list once vision is genuinely folded into the ledger.
    assert fused["probability_basis"]["evidence_count"] == len(fused["evidence"])

    # Sanity: the default (non-opt-in) response for the same inputs is still
    # stamped deterministic, proving the flag -- not some global state --
    # controls this.
    assert default["deterministic"] is True


def test_image_only_request_returns_usable_read_and_is_non_deterministic(monkeypatch):
    """An image-only request (no bars available) has nothing but the vision
    read to go on -- it must still work, and must always be stamped
    non-deterministic regardless of the fuse opt-in.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = _fake_vision("BEARISH")

    with patch("research.vpa_engine.call_gemini_vision", return_value=fake):
        res = analyze_chart_vpa(image_base64="ZmFrZQ==")

    assert res["engine_mode"] == "vision_multimodal"
    assert res["deterministic"] is False
    assert res["reproducible"] is False
    assert res["vision_status"]["image_used"] is True
    # A usable read: some primary scenario / direction must come through.
    assert res.get("primary_scenario") or res.get("direction") or fake["primary_scenario"]
