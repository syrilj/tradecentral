import pytest
from research.ta_levels import (
    calculate_atr,
    find_swing_extrema,
    measure_symbol_ta_levels,
    load_symbol_daily_bars,
)
import numpy as np


class TestTaLevels:
    def test_calculate_atr(self):
        highs = np.array([10, 11, 12, 13, 14, 15], dtype=float)
        lows = np.array([8, 9, 10, 11, 12, 13], dtype=float)
        closes = np.array([9, 10, 11, 12, 13, 14], dtype=float)
        atr = calculate_atr(highs, lows, closes, period=3)
        assert atr is not None
        assert atr > 0

    def test_find_swing_extrema(self):
        highs = np.array([10, 12, 15, 13, 11, 14, 17, 13, 12], dtype=float)
        lows = np.array([8, 10, 11, 9, 7, 10, 12, 10, 9], dtype=float)
        spot = 12.5
        swing_lows, swing_highs = find_swing_extrema(highs, lows, spot=spot, window=1)
        assert all(low < spot for low in swing_lows)
        assert all(high > spot for high in swing_highs)

    def test_measure_symbol_ta_levels_on_disk(self):
        levels = measure_symbol_ta_levels("AMD")
        if levels:
            assert levels["symbol"] == "AMD"
            assert levels["spot"] > 0
            assert levels["ta_support"] is not None
            assert levels["ta_resistance"] is not None
            assert levels["ta_support"] < levels["spot"]
            assert levels["ta_resistance"] > levels["spot"]
            assert len(levels["supports"]) > 0
            assert len(levels["resistances"]) > 0
            assert all(item["source"] == "technical analysis" for item in levels["supports"])
            assert all(item["source"] == "technical analysis" for item in levels["resistances"])
