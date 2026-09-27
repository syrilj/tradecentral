"""The ticket's stop, targets and size must come from measured bar risk.

These lock the fix for the CRDO regression: stops and targets were multiples of
``NadarayaWatsonEnvelopeResult.sigma_local``, the kernel-weighted dispersion of
price *levels* over a long lookback. On a name that had travelled from $80 to
$270 that quantity was $29 against a $9 implied daily move, so a "1.5 sigma"
stop sat 23% above spot and the "3 sigma" target implied a 45% fall by
tomorrow. The ticket read as arithmetic but measured channel width, not risk.
"""
from __future__ import annotations

import numpy as np
import pytest

from edge.research.systematic_execution import (
    MAX_SINGLE_NAME_PCT,
    compute_bar_volatility_unit,
    generate_microstructure_signals,
)


def _trending_bars(n: int = 260, seed: int = 7) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A long uptrend that ends in a sharp break -- CRDO's shape."""
    rng = np.random.default_rng(seed)
    ramp = np.linspace(80.0, 270.0, n - 10)
    noise = rng.normal(0.0, 2.0, n - 10)
    closes = np.concatenate([ramp + noise, np.linspace(268.0, 165.0, 10)])
    highs = closes * 1.02
    lows = closes * 0.98
    return closes, highs, lows


class TestBarVolatilityUnit:
    def test_atr_is_used_when_highs_and_lows_are_supplied(self):
        closes, highs, lows = _trending_bars()
        unit, basis = compute_bar_volatility_unit(closes, highs=highs, lows=lows)
        assert basis == "atr"
        assert unit.shape == closes.shape
        assert np.all(unit > 0)

    def test_implied_vol_wins_over_atr_and_matches_the_rule_of_16(self):
        closes, highs, lows = _trending_bars(n=40)
        iv = np.full(len(closes), 0.88)
        unit, basis = compute_bar_volatility_unit(closes, highs=highs, lows=lows, iv_series=iv)
        assert basis == "implied_1bar"
        # Rule of 16: a one-day 1-sigma move is S * IV / sqrt(252).
        expected = closes[-1] * 0.88 / np.sqrt(252.0)
        assert unit[-1] == pytest.approx(expected, rel=1e-9)

    def test_percentage_and_fractional_iv_are_read_the_same_way(self):
        closes, _, _ = _trending_bars(n=30)
        as_pct, _ = compute_bar_volatility_unit(closes, iv_series=np.full(len(closes), 88.0))
        as_frac, _ = compute_bar_volatility_unit(closes, iv_series=np.full(len(closes), 0.88))
        assert as_pct[-1] == pytest.approx(as_frac[-1], rel=1e-9)

    def test_close_to_close_fallback_when_no_ohlc_and_no_iv(self):
        closes, _, _ = _trending_bars(n=60)
        unit, basis = compute_bar_volatility_unit(closes)
        assert basis == "close_to_close"
        assert np.all(unit >= 0.0025 * closes)

    def test_unit_is_far_smaller_than_the_kernel_channel_width(self):
        """The regression itself: the two quantities are not interchangeable."""
        from edge.research.state_estimation import causal_nadaraya_watson_envelope

        closes, highs, lows = _trending_bars()
        unit, _ = compute_bar_volatility_unit(closes, highs=highs, lows=lows)
        nw = causal_nadaraya_watson_envelope(closes, base_bandwidth=20.0, alpha=2.0)
        assert unit[-1] < nw.sigma_local[-1]


class TestTicketArithmetic:
    @staticmethod
    def _entries(**kw):
        closes, highs, lows = _trending_bars()
        signals, *_ = generate_microstructure_signals(
            closes, highs=highs, lows=lows, symbol="TEST", **kw
        )
        return [s for s in signals if s.action in {"ENTER_LONG", "ENTER_SHORT"}]

    def test_some_tickets_are_produced(self):
        assert self._entries(), "fixture must exercise the entry branches"

    def test_stop_sits_on_the_correct_side_of_entry(self):
        for s in self._entries():
            if s.direction == "long":
                assert s.stop_loss < s.entry_price
                assert s.take_profit > s.entry_price
            else:
                assert s.stop_loss > s.entry_price
                assert s.take_profit < s.entry_price

    def test_stop_distance_is_within_two_bar_sigmas(self):
        """A stop is a volatility distance. 1.5 * sigma_local was 26% of spot."""
        for s in self._entries():
            assert abs(s.entry_price - s.stop_loss) <= 2.0 * s.risk_unit + 1e-6

    def test_r_ladder_is_measured_off_the_quoted_stop(self):
        for s in self._entries():
            r = abs(s.entry_price - s.stop_loss)
            sign = 1.0 if s.direction == "long" else -1.0
            assert s.target_1r == pytest.approx(round(s.entry_price + sign * r, 2), abs=0.011)
            assert s.target_2r == pytest.approx(round(s.entry_price + sign * 2 * r, 2), abs=0.011)
            assert s.target_3r == pytest.approx(round(s.entry_price + sign * 3 * r, 2), abs=0.011)

    def test_reward_to_risk_is_reported_and_between_one_and_three(self):
        for s in self._entries():
            r = abs(s.entry_price - s.stop_loss)
            assert s.risk_reward == pytest.approx(abs(s.take_profit - s.entry_price) / r, abs=0.02)
            assert 1.0 <= s.risk_reward <= 3.01

    def test_size_is_solved_from_the_stop_not_scaled_off_conviction(self):
        for s in self._entries():
            assert 0 < s.suggested_size_pct <= MAX_SINGLE_NAME_PCT
            # Loss at the stop, as a percentage of capital, stays inside the
            # 0.25%-1.00% risk budget. `conviction * 10` had no such bound.
            risk_pct = s.suggested_size_pct * abs(s.entry_price - s.stop_loss) / s.entry_price
            assert risk_pct <= 1.0 + 1e-6

    def test_basis_is_declared_on_every_ticket(self):
        for s in self._entries():
            assert s.risk_unit_basis in {"implied_1bar", "atr", "close_to_close"}
            assert s.risk_unit > 0

    def test_implied_vol_reprices_the_whole_ticket(self):
        closes, highs, lows = _trending_bars()
        iv = np.full(len(closes), 0.30)
        with_iv = [
            s
            for s in generate_microstructure_signals(
                closes, highs=highs, lows=lows, iv_series=iv, symbol="TEST"
            )[0]
            if s.action in {"ENTER_LONG", "ENTER_SHORT"}
        ]
        assert with_iv
        for s in with_iv:
            assert s.risk_unit_basis == "implied_1bar"
            assert s.risk_unit == pytest.approx(s.entry_price * 0.30 / np.sqrt(252.0), rel=1e-3)
