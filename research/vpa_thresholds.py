"""Single source of truth for every numeric threshold used by the VPA engine.

Contract: `docs/VPA_REBUILD_CONTRACT.md` §5/§6 require that all tuning constants
live in ONE module-level dict so the engine is trivially retunable.

Why a fourth module rather than a dict inside one of the three named in §3:
`vpa_bars`, `vpa_levels` and `vpa_score` all need the same constants and
`vpa_score` imports `vpa_levels`, so hosting the dict in either would either
create an import cycle or force one module to import a sibling it has no other
business knowing about. Recorded in the contract's Deviations section.

**Provenance of the numbers below.** Every constant is an original ratio against
a trailing baseline: "high volume" and "narrow spread" are relative to recent
bars on the same symbol, not fixed ticks. `book_spec_status()` reports that
these defaults are the thresholds in force.
"""

from __future__ import annotations

from typing import Any, Dict


VPA_THRESHOLDS: Dict[str, Any] = {
    # ---------------------------------------------------------------- bars --
    "bars": {
        # Default lookback per served timeframe. Chosen so every timeframe gets
        # a comparable amount of *calendar* history (~1 to 1.5 years) rather
        # than a comparable bar count. Congestion is read in calendar time.
        "default_lookback": {
            "1h": 420,   # ~60 US sessions of 7 hourly bars
            "2h": 300,
            "4h": 250,
            "1D": 300,   # ~14 months
            "1W": 200,   # ~4 years
        },
        "fallback_lookback": 300,
        # Below this the engine refuses to score: fewer bars than the volume
        # baseline window plus a pivot confirmation window on each side means
        # there is no "previous bars" context to be relative to.
        "min_bars_for_analysis": 30,
    },
    # -------------------------------------------------------------- levels --
    "levels": {
        # Fractal pivot confirmation, n bars either side. "isolated
        # pivot high/low" is drawn by eye; 3/3 is the smallest window that
        # rejects single-bar noise while still catching intraday swing points.
        "pivot_left": 3,
        "pivot_right": 3,
        # Zone clustering tolerance, in ATR units. Floors and ceilings are
        # zones with width, not lines; one half of an average bar's
        # true range is the width at which two pivots visibly belong to the
        # same band on a chart.
        "cluster_atr_mult": 0.55,
        # A zone must be padded to at least this fraction of ATR so a single
        # pivot still produces a drawable band rather than a zero-width line.
        "min_zone_atr_mult": 0.18,
        # Pivot highs and pivot lows are clustered separately, so a ceiling
        # and a floor found at the same price arrive as two zones. Two bands
        # overlapping by more than this fraction of the narrower one are the
        # same level and are folded together; left apart, every break through
        # them is counted once per copy.
        "zone_merge_overlap": 0.5,
        "atr_period": 14,
        # A bar "touches" a zone when its high/low range intersects the band.
        # Zones with fewer than this many touches are dropped as noise: a level
        # nobody traded twice is not a level.
        "min_touches": 2,
        # Recency decay half-life in bars. A ceiling last tested 200 bars ago
        # is real but stale; halving its strength every `strength_half_life`
        # bars encodes "the market has to remember the level".
        "strength_half_life": 60.0,
        # Strength blend weights (must sum to 1.0).
        "strength_touch_weight": 0.45,
        "strength_recency_weight": 0.35,
        "strength_pivot_weight": 0.20,
        # Touch count at which the touch component saturates.
        "touch_saturation": 5,
        "max_zones": 8,
        # A band sitting on top of the current price is not something price has
        # to travel to, so it is reported in `levels[]` but never used as the
        # actionable floor/ceiling for a stop or target. Without this the
        # "nearest resistance" is whatever band the last bar happens to be
        # inside, and the resulting R:R is noise.
        "min_actionable_distance_atr": 0.75,
        # Breakout validation (Ch.7). "Clear water" = the close must sit this
        # many ATRs clear of the zone edge; a close *on* the band is not a
        # break. Volume must also be rising versus the trailing baseline, else
        # the move is a fakeout, not a breakout.
        "clear_water_atr_mult": 0.30,
        "breakout_volume_ratio": 1.30,
        "breakout_fakeout_volume_ratio": 0.90,
        # How far back to look for the bar that actually crossed the band. Wide
        # enough that a break a few weeks old is still the reason price sits
        # where it does.
        "breakout_scan_bars": 30,
        # A break is live evidence only while it is still recent and still
        # near the auction. A band crossed long ago and left several ATR
        # behind is history: reporting it as a current signal reads the past.
        "breakout_max_age_bars": 15,
        "breakout_max_distance_atr": 2.5,
        # Role reversal (Ch.7): after a confirmed break, the broken zone flips
        # role. We only claim the flip once the break is this many bars old
        # enough to have closed beyond the band.
        "role_reversal_min_bars": 1,
    },
    # ----------------------------------------------------------------- vap --
    "vap": {
        # 24 bins over the visible range: fine enough that a high-volume node
        # is distinguishable from its neighbours, coarse enough that each bin
        # collects volume from many bars.
        "bins": 24,
        # the engine/Market-Profile convention: the value area is the contiguous
        # band around the POC holding 70% of traded volume.
        "value_area_pct": 0.70,
    },
    # ------------------------------------------------------------- signals --
    "signals": {
        # Volume classification, as a ratio to the trailing baseline average
        # (exclusive of the bar being judged -- reads each bar against
        # the bars *before* it).
        "volume_baseline_bars": 20,
        # Time-of-day (slot) baseline for intraday timeframes (1h/2h/4h).
        # Volume and session range both have a strong intraday U-shape -- the
        # 09:30 bar routinely carries two to three times a midday bar's
        # volume -- so a flat trailing-N-bar window mixes hour-of-day slots
        # and makes "ultra high volume" fire structurally at the open and
        # "low volume" fire structurally at 12:30-13:30, independent of what
        # the market actually did that day (docs/audits/
        # 2026-09-01-vwap-orderflow-evaluation.md §2.1). When the bar under
        # judgement is intraday, its baseline is instead built from the SAME
        # hour-of-day slot over the trailing sessions, strictly exclusive of
        # the current bar. How many trailing same-slot occurrences to look
        # back through.
        "volume_baseline_sessions": 30,
        # Below this many same-slot samples a slot baseline is too thin to
        # trust (e.g. a symbol with only a few weeks of hourly history);
        # fall back to the existing trailing all-bar window so behaviour
        # degrades gracefully rather than emitting nothing.
        "volume_baseline_min_slot_samples": 10,
        # Central-tendency estimator for the slot baseline. A mean is
        # dominated by the single largest recent spike on a heavy-tailed
        # volume series, which makes a genuine second climax look merely
        # "above average" (audit §2.1, secondary issue); median is more
        # robust to that. Kept as a switch, not hardcoded, and scoped to the
        # slot baseline only -- the legacy trailing all-bar fallback (used
        # for daily/weekly bars and for thin slot history) stays a mean so
        # non-intraday behaviour is provably unchanged by this fix.
        "volume_baseline_estimator": "median",
        "vol_ultra_high": 2.00,
        "vol_high": 1.35,
        "vol_low": 0.75,
        "vol_ultra_low": 0.55,
        # Spread classification against the trailing average true range.
        "spread_wide": 1.25,
        "spread_narrow": 0.70,
        # Wick geometry for the candle taxonomy (Ch.5).
        "wick_dominant": 0.50,     # wick >= 50% of range = "long" wick
        "wick_suppressed": 0.28,   # opposite wick must stay under this
        "doji_body": 0.15,         # body <= 15% of range
        "close_upper_third": 0.66,
        "close_lower_third": 0.34,
        # How many trailing bars a detector is allowed to look at. the engine's
        # "Step 2 (Macro)" reads a local cluster of 3-10 candles; we widen to
        # 20 so a multi-bar campaign phase is visible.
        "scan_window": 20,
        # Trend context window used to decide whether a climax is stopping
        # (down move ending) or topping (up move ending).
        "trend_window": 10,
        "trend_move_pct": 0.02,
        # Trending-vs-ranging for the phase label, in ATR units rather than
        # percent: a flat 2% is half a bar's range for a quiet name and a
        # third of one for a volatile name, so it asks a different question of
        # every instrument. One average bar's range travelled across the whole
        # scan window is the same question everywhere.
        "trend_move_atr": 1.0,
        # Recency weighting of evidence: an anomaly 40 bars back matters less
        # than one on the last bar. Half-life in bars.
        "evidence_half_life": 12.0,
        # Evidence weaker than this is dropped so the ledger stays readable.
        "min_evidence_weight": 0.015,
        "max_evidence_items": 24,
    },
    # ------------------------------------------------------- signal weights --
    # Base weights before recency decay. Ordered by how load-bearing the signal
    # is in the book: climactic volume and confirmed breakouts are the engine's
    # highest-conviction reads; positional signals (where price sits versus the
    # POC) are context, not conviction.
    "weights": {
        "stopping_volume": 0.30,
        "topping_out_volume": 0.30,
        "selling_climax": 0.26,
        "buying_climax": 0.26,
        "breakout_confirmed": 0.28,
        "fakeout_risk": 0.24,
        "role_reversal": 0.20,
        "low_volume_test": 0.22,
        "no_supply": 0.18,
        "no_demand": 0.18,
        "hammer": 0.16,
        "shooting_star": 0.16,
        "hanging_man": 0.14,
        "long_legged_doji": 0.10,
        "effort_result_validation": 0.14,
        "effort_result_anomaly": 0.20,
        "absorption_churn": 0.18,
        "value_area_position": 0.08,
        "trend_context": 0.10,
        "vision_agreement": 0.20,
    },
    # ------------------------------------------------------------- scoring --
    "scoring": {
        # The logistic reads the *balance* of the ledger, not its size: the net
        # score is first divided by (total evidence mass + prior_mass). Without
        # that normalisation a busy 20-bar window pins every symbol to the
        # ceiling simply because it fired a lot of detectors, which is how you
        # end up back at a constant. `prior_mass` is the weight of the implicit
        # "no signal" prior, so a thin ledger cannot swing to an extreme.
        "logistic_k": 2.60,
        "prior_mass": 0.75,
        # Contract §5: VPA reads direction, it is not a calibrated forecaster.
        "probability_floor": 35,
        "probability_ceiling": 80,
        # |p_bull - 0.5| below this reads as no directional edge.
        "neutral_band": 0.035,
    },
    # ---------------------------------------------------------- confidence --
    "confidence": {
        # Bar count at which the coverage component saturates.
        "full_coverage_bars": 150,
        # Evidence count at which the density component saturates.
        "full_density_items": 8,
        "weight_coverage": 0.30,
        "weight_agreement": 0.34,
        "weight_recency": 0.18,
        "weight_density": 0.18,
        # Data staleness, in *bars* of the served timeframe, before the recency
        # component starts decaying (markets move; a 3-month-old last bar is
        # not a live read).
        "stale_after_days": {"1h": 5, "2h": 5, "4h": 7, "1D": 5, "1W": 21},
        "stale_decay_days": 45.0,
        # Multiplicative penalty when the requested timeframe was downgraded.
        "downgrade_penalty": 0.72,
        # Ceiling on the *method itself*. Even a perfect data situation -- deep
        # history, fresh bars, a one-sided ledger -- is still a discretionary
        # reading of candle geometry, so the components are scaled by this
        # before the clamp. Confidence near 1.0 would be the same overclaim
        # this rebuild exists to remove.
        "method_ceiling": 0.85,
        "floor": 0.12,
        "ceiling": 0.85,
    },
    # --------------------------------------------------------------- trade --
    "trade": {
        # Stop is placed beyond the level, not on it (the engine: use natural
        # market-defined barriers, then leave room beyond the zone).
        "stop_atr_pad": 0.35,
        # A target closer than this many ATRs is not worth quoting.
        "min_target_atr": 0.5,
        "min_risk_atr": 0.10,
        "rr_round": 2,
    },
}


# Internal rule ids. These name the engine's own checks. They are not citations
# of a third-party book.
BOOK_REFS: Dict[str, str] = {
    "supply_demand": "rule.supply-demand",
    "cause_effect": "rule.cause-effect",
    "effort_result": "rule.effort-result",
    "candle_anatomy": "rule.candle-anatomy",
    "shooting_star": "rule.shooting-star",
    "hammer": "rule.hammer",
    "hanging_man": "rule.hanging-man",
    "long_legged_doji": "rule.long-legged-doji",
    "no_demand": "rule.no-demand",
    "no_supply": "rule.low-volume-supply-test",
    "stopping_volume": "rule.stopping-volume",
    "topping_volume": "rule.topping-volume",
    "selling_climax": "rule.selling-climax",
    "buying_climax": "rule.buying-climax",
    "testing": "rule.supply-demand-test",
    "absorption": "rule.absorption",
    "support_resistance": "rule.support-resistance",
    "breakout": "rule.breakout",
    "role_reversal": "rule.role-reversal",
    "volume_at_price": "rule.volume-at-price",
    "multi_timeframe": "rule.multi-timeframe",
    "vision_agreement": "rule.chart-agreement",
}


def book_spec_status() -> Dict[str, Any]:
    """Report that thresholds come from this module."""
    return {
        "spec_present": False,
        "spec_path": "research/vpa_thresholds.py",
        "thresholds_source": "research/vpa_thresholds.py",
        "provisional": False,
        "note": "Thresholds are original ratios in research/vpa_thresholds.py.",
    }
