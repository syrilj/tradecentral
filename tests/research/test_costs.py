from __future__ import annotations

import pandas as pd
import pytest

from edge.research.costs import UnderlyingCostModel, directional_underlying_return, directional_underlying_returns


def test_long_short_signs_and_zero_move_are_conservative_after_round_trip_costs() -> None:
    costs = UnderlyingCostModel(one_way_spread_bps=5, one_way_slippage_bps=2, one_way_fee_bps=1)
    long = directional_underlying_return(entry_close=100, exit_close=110, position="long", costs=costs)
    short = directional_underlying_return(entry_close=100, exit_close=90, position=-1, costs=costs)
    flat = directional_underlying_return(entry_close=100, exit_close=100, position="flat", costs=costs)
    zero_move = directional_underlying_return(entry_close=100, exit_close=100, position="short", costs=costs)
    assert long.gross_return == pytest.approx(.10) and long.net_return == pytest.approx(.0984)
    assert short.gross_return == pytest.approx(.10) and short.net_return == pytest.approx(.0984)
    assert long.round_trip_cost_bps == 16
    assert flat.gross_return == flat.net_return == 0 and flat.round_trip_cost_bps == 0
    assert zero_move.gross_return == 0 and zero_move.net_return == pytest.approx(-.0016)


def test_rows_use_same_symbol_trading_dates_and_all_frozen_horizons() -> None:
    dates = pd.bdate_range("2026-01-02", periods=22)
    rows = pd.DataFrame({"symbol": ["AAA"] * len(dates), "trading_date": dates,
                         "close": range(100, 122), "signal": ["long"] * len(dates)})
    costs = UnderlyingCostModel(one_way_spread_bps=1)
    for horizon in (5, 10, 20):
        result = directional_underlying_returns(rows, horizon_days=horizon, costs=costs, signal_col="signal")
        assert set(result["instrument"]) == {"underlying"}
        assert set(result["return_basis"]) == {"underlying_close_to_close"}
        assert result.loc[0, "target_end"] == dates[horizon]
        assert result.loc[0, "gross_return"] == pytest.approx(horizon / 100)
        assert result.loc[0, "net_return"] == pytest.approx(horizon / 100 - .0002)
        assert result["net_return"].tail(horizon).isna().all()


def test_no_lookahead_after_resolved_target_and_validation_is_fail_closed() -> None:
    dates = pd.bdate_range("2026-01-02", periods=30)
    rows = pd.DataFrame({"trading_date": dates, "close": range(100, 130), "position": [1] * 30})
    before = directional_underlying_returns(rows, horizon_days=5)
    changed = rows.copy(); changed.loc[15:, "close"] *= 10
    after = directional_underlying_returns(changed, horizon_days=5)
    pd.testing.assert_frame_equal(before.iloc[:10], after.iloc[:10])
    with pytest.raises(ValueError, match="sorted"):
        directional_underlying_returns(rows.iloc[::-1], horizon_days=5)
    with pytest.raises(ValueError, match="frozen"):
        directional_underlying_returns(rows, horizon_days=4)
    with pytest.raises(ValueError, match="exactly"):
        directional_underlying_returns(rows.assign(position=2), horizon_days=5)
