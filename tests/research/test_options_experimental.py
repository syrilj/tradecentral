"""
Unit tests for Workstream 4: Experimental Options Features & Unbiased GEX Engine.
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

try:
    from edge.research.gex_model import (
        compute_dollar_gamma,
        compute_unbiased_gex_profile,
    )
    from edge.research.options_features import (
        compute_iv_skew_metrics,
        ExperimentalOptionsGate,
    )
except ImportError:
    from research.gex_model import (
        compute_dollar_gamma,
        compute_unbiased_gex_profile,
    )
    from research.options_features import (
        compute_iv_skew_metrics,
        ExperimentalOptionsGate,
    )


def test_dollar_gamma_calculation():
    # OI = 1000, Gamma = 0.05, Spot = 100.0
    # DollarGamma = 1000 * 100 * 0.05 * 100^2 * 0.01 = 500,000 USD
    dg = compute_dollar_gamma(open_interest=1000, gamma=0.05, spot_price=100.0)
    assert dg == pytest.approx(500_000.0, abs=1e-2)


def test_unbiased_gex_profile():
    chain = pd.DataFrame([
        {"strike": 100.0, "option_type": "CALL", "open_interest": 1000, "gamma": 0.05, "days_to_expiration": 5},
        {"strike": 105.0, "option_type": "CALL", "open_interest": 500,  "gamma": 0.02, "days_to_expiration": 15},
        {"strike": 95.0,  "option_type": "PUT",  "open_interest": 1200, "gamma": 0.04, "days_to_expiration": 40},
    ])

    profile = compute_unbiased_gex_profile(chain, spot_price=100.0)
    assert profile.spot_price == 100.0
    assert profile.total_abs_gamma_usd > 0
    assert profile.call_gamma_usd > 0
    assert profile.put_gamma_usd > 0
    assert "atm" in profile.gamma_by_strike_distance
    assert "0-7d" in profile.gamma_by_expiration


def test_implied_volatility_features():
    # ATM IV = 20%, 25d Put IV = 24%, 25d Call IV = 18%
    # Put Skew = 24% - 20% = +4% (0.04)
    # Risk Reversal = 24% - 18% = +6% (0.06)
    # Butterfly = (24% + 18%)/2 - 20% = 21% - 20% = +1% (0.01)
    metrics = compute_iv_skew_metrics(
        iv_atm=0.20,
        iv_25d_put=0.24,
        iv_25d_call=0.18,
    )

    assert metrics.put_skew_25d == pytest.approx(0.04, abs=1e-4)
    assert metrics.risk_reversal_25d == pytest.approx(0.06, abs=1e-4)
    assert metrics.butterfly_25d == pytest.approx(0.01, abs=1e-4)


def test_options_experimental_gate():
    gate_unvalidated = ExperimentalOptionsGate(is_equity_pipeline_validated=False)
    # Equity pipeline not valid -> options features BLOCKED regardless of lift
    assert not gate_unvalidated.can_include_options_features(oos_net_sharpe_lift=0.50)

    gate_validated = ExperimentalOptionsGate(is_equity_pipeline_validated=True)
    # Insufficient lift -> BLOCKED
    assert not gate_validated.can_include_options_features(oos_net_sharpe_lift=0.01)
    # Sufficient lift -> ALLOWED
    assert gate_validated.can_include_options_features(oos_net_sharpe_lift=0.15)
