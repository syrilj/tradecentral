from __future__ import annotations


import pytest

from edge.daily_plays.options_fills import (
    OptionsFillModel,
    entry_fill_price,
    normalize_side,
    round_trip_option_return,
    spread_fill,
)


def test_buying_fills_at_ask_never_at_mid_on_default_settings() -> None:
    result = entry_fill_price(bid=1.00, ask=1.20, side="buy")
    assert result.filled is True
    assert result.price == pytest.approx(1.20)
    assert result.reference_mid == pytest.approx(1.10)
    assert result.price != result.reference_mid


def test_selling_fills_at_bid_never_at_mid_on_default_settings() -> None:
    result = entry_fill_price(bid=1.00, ask=1.20, side="sell")
    assert result.filled is True
    assert result.price == pytest.approx(1.00)
    assert result.reference_mid == pytest.approx(1.10)
    assert result.price != result.reference_mid


def test_slippage_vs_mid_is_always_nonnegative_in_cost_terms_both_sides() -> None:
    buy = entry_fill_price(bid=2.00, ask=2.10, side="buy")
    sell = entry_fill_price(bid=2.00, ask=2.10, side="sell")
    assert buy.slippage_vs_mid >= 0
    assert sell.slippage_vs_mid >= 0
    assert buy.slippage_vs_mid == pytest.approx(0.05)
    assert sell.slippage_vs_mid == pytest.approx(0.05)


def test_spread_wider_than_max_returns_no_fill_with_reason_and_no_price() -> None:
    model = OptionsFillModel(max_spread_pct=0.10)
    # spread_pct = (1.50 - 1.00) / 1.25 = 0.40 > 0.10
    result = entry_fill_price(bid=1.00, ask=1.50, side="buy", model=model)
    assert result.filled is False
    assert result.price is None
    assert result.reason is not None and "spread_pct" in result.reason


def test_round_trip_on_unchanged_quote_is_strictly_negative_buy_side() -> None:
    result = round_trip_option_return(
        entry_bid=1.00, entry_ask=1.20, exit_bid=1.00, exit_ask=1.20, side="buy",
    )
    assert result.filled is True
    assert result.net_return is not None and result.net_return < 0
    assert result.gross_return is not None and result.gross_return < 0


def test_round_trip_on_unchanged_quote_is_strictly_negative_sell_side() -> None:
    result = round_trip_option_return(
        entry_bid=1.00, entry_ask=1.20, exit_bid=1.00, exit_ask=1.20, side="sell",
    )
    assert result.filled is True
    assert result.net_return is not None and result.net_return < 0
    assert result.gross_return is not None and result.gross_return < 0


def test_mid_to_mid_return_on_unchanged_quote_documents_the_fiction_as_zero() -> None:
    result = round_trip_option_return(
        entry_bid=1.00, entry_ask=1.20, exit_bid=1.00, exit_ask=1.20, side="buy",
    )
    assert result.mid_to_mid_return == pytest.approx(0.0)
    # The naive mid-to-mid figure hides the entire round-trip cost this
    # module exists to surface.
    assert result.mid_to_mid_return > result.net_return


def test_round_trip_fees_scale_total_fees_with_contracts() -> None:
    model = OptionsFillModel(fee_per_contract=0.65)
    one = round_trip_option_return(
        entry_bid=1.00, entry_ask=1.20, exit_bid=1.00, exit_ask=1.20, side="buy",
        contracts=1, model=model,
    )
    five = round_trip_option_return(
        entry_bid=1.00, entry_ask=1.20, exit_bid=1.00, exit_ask=1.20, side="buy",
        contracts=5, model=model,
    )
    assert one.total_fees == pytest.approx(0.65 * 2)
    assert five.total_fees == pytest.approx(0.65 * 2 * 5)


def test_round_trip_unfilled_leg_never_substitutes_a_price() -> None:
    model = OptionsFillModel(max_spread_pct=0.10)
    result = round_trip_option_return(
        entry_bid=1.00, entry_ask=1.20,  # spread too wide under this model
        exit_bid=1.00, exit_ask=1.05,
        side="buy", model=model,
    )
    assert result.filled is False
    assert result.gross_return is None
    assert result.net_return is None
    assert result.entry_price is None
    assert result.exit_price is None
    assert result.reason is not None and "entry" in result.reason


def test_multi_leg_one_bad_leg_fails_the_entire_spread() -> None:
    good_leg = {"bid": 1.00, "ask": 1.10, "ratio": 1}
    bad_leg = {"bid": 0.50, "ask": 2.00, "ratio": -1}  # spread too wide by default (0.25)
    result = spread_fill(legs=[good_leg, bad_leg], side="buy")
    assert result.filled is False
    assert result.price is None
    assert result.reason is not None and "leg 1" in result.reason


def test_multi_leg_debit_spread_fills_at_sum_of_conservative_legs() -> None:
    long_leg = {"bid": 1.00, "ask": 1.10, "ratio": 1}
    short_leg = {"bid": 0.40, "ask": 0.50, "ratio": -1}
    result = spread_fill(legs=[long_leg, short_leg], side="buy")
    assert result.filled is True
    # long leg buys at ask (1.10), short leg sells at bid (0.40)
    assert result.price == pytest.approx(1.10 - 0.40)
    assert result.slippage_vs_mid >= 0


@pytest.mark.parametrize("bid,ask", [
    (float("nan"), 1.20),
    (1.00, float("inf")),
    (0.0, 1.20),
    (-1.0, 1.20),
    (1.20, 1.00),  # inverted: ask <= bid
    (1.00, 1.00),  # inverted: ask == bid
])
def test_degenerate_quotes_never_produce_a_number(bid, ask) -> None:
    result = entry_fill_price(bid=bid, ask=ask, side="buy")
    assert result.filled is False
    assert result.price is None
    assert result.reason is not None


def test_non_numeric_quote_never_produces_a_number() -> None:
    result = entry_fill_price(bid="not-a-price", ask=1.20, side="buy")
    assert result.filled is False
    assert result.price is None
    assert result.reason is not None


@pytest.mark.parametrize("bad_side", ["long_call", "purchase", "", None, 1, 0, True])
def test_invalid_side_strings_raise_value_error(bad_side) -> None:
    with pytest.raises(ValueError):
        entry_fill_price(bid=1.00, ask=1.20, side=bad_side)


def test_normalize_side_accepts_documented_vocabulary_only() -> None:
    assert normalize_side("buy") == "buy"
    assert normalize_side("debit") == "buy"
    assert normalize_side("SELL") == "sell"
    assert normalize_side("credit") == "sell"
    with pytest.raises(ValueError):
        normalize_side("neutral")


def test_options_fill_model_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        OptionsFillModel(patience_fraction=1.5)
    with pytest.raises(ValueError):
        OptionsFillModel(max_spread_pct=0.0)
    with pytest.raises(ValueError):
        OptionsFillModel(fee_per_contract=-0.01)
    with pytest.raises(ValueError):
        OptionsFillModel(cross_after_bars=-1)
    with pytest.raises(ValueError):
        OptionsFillModel(stale_quote_bars=-1)


def test_round_trip_contracts_must_be_a_positive_integer() -> None:
    with pytest.raises(ValueError):
        round_trip_option_return(
            entry_bid=1.00, entry_ask=1.20, exit_bid=1.00, exit_ask=1.20,
            side="buy", contracts=0,
        )
    with pytest.raises(ValueError):
        round_trip_option_return(
            entry_bid=1.00, entry_ask=1.20, exit_bid=1.00, exit_ask=1.20,
            side="buy", contracts=1.5,
        )
