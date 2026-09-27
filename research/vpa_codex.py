"""Volume-price rule catalog used by this workstation.

The labels below are this engine's own wording for generally known market
relationships: supply and demand, cause and effect, and effort versus result.
"""

from __future__ import annotations

from typing import Any, Dict, List

VPA_LAWS = [
    {
        "id": "law_supply_demand",
        "name": "The Law of Supply and Demand",
        "origin": "Richard Wyckoff",
        "principle": "When demand is greater than supply, price rises. When supply is greater than demand, price falls.",
        "vpa_application": "Volume reveals whether demand or supply is driving the price action bar-by-bar.",
    },
    {
        "id": "law_cause_effect",
        "name": "The Law of Cause and Effect",
        "origin": "Richard Wyckoff",
        "principle": "In order to have an effect, you must first have a cause, and the effect is in direct proportion to the cause.",
        "vpa_application": "The duration, depth, and volume accumulation during a congestion phase (cause) dictates the scale and time duration of the subsequent breakout trend (effect).",
    },
    {
        "id": "law_effort_result",
        "name": "The Law of Effort vs Result",
        "origin": "Richard Wyckoff",
        "principle": "Every action has an equal and opposite reaction. The price spread (result) must reflect the volume action (effort).",
        "vpa_application": "If volume (effort) and price spread (result) are in harmony, the move is validated. If they diverge, an anomaly is signaled (e.g. trap up move, absorption, topping/stopping volume).",
    },
]

VPA_CORE_PRINCIPLES = [
    {
        "number": 1,
        "name": "Relative, not absolute",
        "summary": "Compare the current spread and wick to recent volume on the same symbol and timeframe.",
    },
    {
        "number": 2,
        "name": "Reversals take time",
        "summary": "A trend usually slows through several bars before it turns. One bar is not a reversal by itself.",
    },
    {
        "number": 3,
        "name": "It's All Relative",
        "summary": "Volume must be judged relative to preceding volume bars in the same instrument and timeframe, rather than absolute numbers.",
    },
    {
        "number": 4,
        "name": "Context in Trend is Paramount",
        "summary": "A candle's meaning depends entirely on where it appears in the broader trend (e.g., a hammer at the bottom is stopping volume; a hammer-like candle at the top is a hanging man signaling weakness).",
    },
    {
        "number": 5,
        "name": "Validation or Anomaly",
        "summary": "Every bar presents only one of two conditions: volume validates price (continuation), or volume shows an anomaly (warning of potential reversal/trap).",
    },
    {
        "number": 6,
        "name": "Three-Step Forensic Process",
        "summary": "Step 1: Micro (single candle vs volume) -> Step 2: Macro (local cluster of 3-5 candles) -> Step 3: Global (entire chart structure, support/resistance, Wyckoff phase).",
    },
]

VPA_CANDLE_TAXONOMY: List[Dict[str, Any]] = [
    {
        "name": "Shooting Star",
        "category": "Premier Reversal Candle",
        "sentiment": "Bearish / Weakness",
        "structure": "Long upper wick (at least 2x body), small real body near the session low, minimal lower wick.",
        "volume_scenarios": {
            "ultra_high": "Major selling climax or heavy institutional dumping. Very strong bearish signal.",
            "average_high": "Clear sign of weakness and selling pressure. Expect pullback or congestion.",
            "low": "Demand test following a selling climax or minor pause. If demand is low, market will drop lower.",
        },
    },
    {
        "name": "Hammer Candle",
        "category": "Premier Reversal Candle",
        "sentiment": "Bullish / Strength",
        "structure": "Long lower wick (at least 2x body), small real body near the session high, minimal upper wick.",
        "volume_scenarios": {
            "ultra_high": "Major buying climax or stopping volume. Insiders aggressively absorbing panic selling.",
            "average_high": "Solid buying support. Good scalping or trend-pause confirmation.",
            "low": "Supply test following accumulation. If selling pressure is absent, price is cleared for markup.",
        },
    },
    {
        "name": "Long-Legged Doji",
        "category": "Premier Indecision Candle",
        "sentiment": "Extreme Volatility / Indecision",
        "structure": "Open and close nearly equal, with long upper and lower wicks.",
        "volume_scenarios": {
            "ultra_high": "Intense battle between buyers and sellers. Potential major trend turning point.",
            "low": "ANOMALY / TRAP: Insiders whipsawing price to trigger stop orders without real volume commitment.",
        },
    },
    {
        "name": "Hanging Man",
        "category": "Warning Candle",
        "sentiment": "Bearish Weakness at Market Top",
        "structure": "Appears at the peak of an uptrend with a long lower wick and small upper body.",
        "volume_scenarios": {
            "above_average": "First warning of serious selling pressure entering the market; requires shooting star confirmation.",
        },
    },
    {
        "name": "Wide Spread Up Candle",
        "category": "Trend Driver",
        "sentiment": "Bullish Momentum",
        "structure": "Large green/blue body with small upper/lower wicks.",
        "volume_scenarios": {
            "high": "VALIDATION: Institutional participation confirming the upward move.",
            "low": "ANOMALY: Trap up move by market makers testing buyer appetite without real commitment.",
        },
    },
    {
        "name": "Wide Spread Down Candle",
        "category": "Trend Driver",
        "sentiment": "Bearish Waterfall",
        "structure": "Large red body with small wicks.",
        "volume_scenarios": {
            "high": "VALIDATION: Genuine institutional liquidation / markdown phase.",
            "low": "ANOMALY: Trap down move / lack of genuine selling conviction.",
        },
    },
    {
        "name": "Narrow Spread Candle",
        "category": "Consolidation / Absorption",
        "sentiment": "Neutral unless High Volume",
        "structure": "Small body and short wicks.",
        "volume_scenarios": {
            "low": "VALIDATION: Normal pause, low market activity.",
            "ultra_high": "MAJOR ANOMALY: Effort without result. At the top: massive institutional distribution into eager buyers. At the bottom: stopping volume absorption.",
        },
    },
]

VPA_CAMPAIGN_PHASES = [
    {
        "phase": "Accumulation",
        "actor": "Insiders / Wholesalers",
        "objective": "Fill warehouses at wholesale prices following a sharp sell-off.",
        "price_action": "Sideways whipsaw within a tight congestion band (defined by isolated pivot low and pivot high).",
        "volume_profile": "High volume spikes on down bars (stopping volume), followed by falling volume on tests.",
    },
    {
        "phase": "Buying Climax",
        "actor": "Insiders absorbing Retail Panic",
        "objective": "The grand finale of accumulation. Insiders absorb the final wave of panic sellers.",
        "price_action": "Multiple hammer candles and narrow spread down candles with long lower wicks.",
        "volume_profile": "Ultra-high / extreme volume bars.",
    },
    {
        "phase": "Testing Supply (Low Volume Test)",
        "actor": "Insiders",
        "objective": "Ensure no remaining supply will dump on the market before launching the markup.",
        "price_action": "Brief dip lower on a narrow candle with lower wick, recovering near open.",
        "volume_profile": "Low volume confirms supply is exhausted and markup is clear to proceed.",
    },
    {
        "phase": "Markup / Bull Trend",
        "actor": "Public Participation & Insiders",
        "objective": "Advance price towards retail target levels.",
        "price_action": "Higher highs and higher lows. Pullbacks are minor.",
        "volume_profile": "Rising volume on up waves; falling volume on pullbacks.",
    },
    {
        "phase": "Distribution",
        "actor": "Insiders selling to Greedy Retail",
        "objective": "Empty warehouses at peak retail prices on wave after wave of bullish news.",
        "price_action": "Narrow trading range near the top. Price unable to advance despite news hype.",
        "volume_profile": "High volume on narrow spreads and shooting stars.",
    },
    {
        "phase": "Selling Climax",
        "actor": "Insiders exiting / Retail FOMO",
        "objective": "The last push of a distribution range before price turns down.",
        "price_action": "Shooting star candles, hanging men, deep upper wicks at resistance ceiling.",
        "volume_profile": "Ultra-high volume without upward price progress.",
    },
    {
        "phase": "Testing Demand (Low Volume Test)",
        "actor": "Insiders",
        "objective": "Verify no aggressive buyers remain before initiating the markdown waterfall.",
        "price_action": "Brief push higher that promptly falls back to open.",
        "volume_profile": "Low volume confirms no buyer demand remains; markdown begins.",
    },
    {
        "phase": "Markdown / Waterfall",
        "actor": "Insiders & Trapped Longs",
        "objective": "A fast decline after distribution, usually faster than the advance that preceded it.",
        "price_action": "Wide spread down candles, gap downs, swift price descent.",
        "volume_profile": "Rising volume on down candles.",
    },
]

VPA_MULTI_TIMEFRAME_MODEL = {
    "framework": "Three timeframes",
    "structure": {
        "fast_lane": "Fast time frame (e.g., 5m) - Early warning signal detector, shows ripples first.",
        "primary_lane": "Middle time frame (e.g., 15m or 1h) - Primary execution and decision chart.",
        "slow_lane": "Slow benchmark time frame (e.g., 30m, 4h, or 1d) - Identifies dominant trend and macro support/resistance.",
    },
    "golden_rule": "Always trade with the flow of the dominant slower timeframe. Counter-trend trades must have tighter stops and shorter duration targets.",
}

VPA_SUPPORT_RESISTANCE_RULES = {
    "house_analogy": "Support and resistance are price zones with width, not single ticks.",
    "role_reversal": "When price breaks through a ceiling on high volume, that ceiling converts into a new floor of support.",
    "breakout_validation": {
        "valid_breakout": "Requires a close outside the zone on strong, rising volume.",
        "fakeout_trap": "Breakout on low or average volume indicates an insider trap; price is likely to revert into congestion.",
    },
    "stop_loss_guidance": "Place stop losses safely beyond the opposite boundary of the congestion zone or beneath the deep wick of the climax candle.",
}


def get_full_vpa_codex() -> Dict[str, Any]:
    """Returns the complete VPA Codex reference dictionary."""
    return {
        "title": "Volume-price rule catalog",
        "author": "TradeCentral",
        "laws": VPA_LAWS,
        "principles": VPA_CORE_PRINCIPLES,
        "candle_taxonomy": VPA_CANDLE_TAXONOMY,
        "campaign_phases": VPA_CAMPAIGN_PHASES,
        "multi_timeframe": VPA_MULTI_TIMEFRAME_MODEL,
        "support_resistance": VPA_SUPPORT_RESISTANCE_RULES,
    }
