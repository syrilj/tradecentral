from dataclasses import replace

import pytest

from edge.daily_plays.config import load_config


def test_preregistered_shadow_option_policy_is_loaded_and_hashed():
    config = load_config()
    assert config.shadow_only is True
    assert (config.swing_dte_min, config.swing_dte_max) == (30, 60)
    assert (config.min_abs_delta, config.max_abs_delta) == (.4, .6)
    assert config.max_spread_pct == .1
    assert (config.min_open_interest, config.min_volume) == (500, 50)
    assert (config.max_position_risk_pct, config.max_underlying_risk_pct,
            config.max_aggregate_open_risk_pct) == (.005, .01, .03)
    assert config.config_hash == load_config().config_hash


@pytest.mark.parametrize("field, value", [
    ("shadow_only", False), ("swing_dte_min", 29), ("max_spread_pct", .11),
    ("min_open_interest", 499), ("max_position_risk_pct", .01),
])
def test_shadow_policy_rejects_diluted_preregistered_limits(field, value):
    with pytest.raises(ValueError):
        replace(load_config(), **{field: value})
