r"""
Experimental Implied Volatility & Options Features Module.

Implements standard constant-maturity options features:
- Put Skew 25-delta: IV_{25\Delta put} - IV_{ATM}
- Risk Reversal 25-delta: IV_{25\Delta put} - IV_{25\Delta call}
- Butterfly 25-delta: (IV_{25\Delta put} + IV_{25\Delta call}) / 2 - IV_{ATM}

Features are normalized against historical distributions and gated as experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OptionsVolatilityMetrics:
    put_skew_25d: float
    risk_reversal_25d: float
    butterfly_25d: float
    normalized_skew_zscore: float
    normalized_rr_zscore: float
    normalized_fly_zscore: float


def compute_iv_skew_metrics(
    iv_atm: float,
    iv_25d_put: float,
    iv_25d_call: float,
    hist_skew_series: Optional[pd.Series] = None,
    hist_rr_series: Optional[pd.Series] = None,
    hist_fly_series: Optional[pd.Series] = None,
) -> OptionsVolatilityMetrics:
    """
    Computes Put Skew, Risk Reversal, Butterfly, and rolling Z-score normalizations.
    """
    if iv_atm <= 0:
        return OptionsVolatilityMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    put_skew = iv_25d_put - iv_atm
    risk_reversal = iv_25d_put - iv_25d_call
    butterfly = 0.5 * (iv_25d_put + iv_25d_call) - iv_atm

    def _zscore(val: float, series: Optional[pd.Series]) -> float:
        if series is None or len(series) < 10:
            return 0.0
        mean = float(series.mean())
        std = float(series.std())
        return (val - mean) / std if std > 0 else 0.0

    return OptionsVolatilityMetrics(
        put_skew_25d=put_skew,
        risk_reversal_25d=risk_reversal,
        butterfly_25d=butterfly,
        normalized_skew_zscore=_zscore(put_skew, hist_skew_series),
        normalized_rr_zscore=_zscore(risk_reversal, hist_rr_series),
        normalized_fly_zscore=_zscore(butterfly, hist_fly_series),
    )


class ExperimentalOptionsGate:
    """
    Gating mechanism to prevent experimental options features from entering
    candidate live models unless explicit OOS net edge is established.
    """
    def __init__(self, is_equity_pipeline_validated: bool = False):
        self.is_equity_pipeline_validated = is_equity_pipeline_validated

    def can_include_options_features(
        self,
        oos_net_sharpe_lift: float,
        complexity_cost_bps: float = 5.0,
    ) -> bool:
        """
        Only allows options features if equity pipeline is valid AND net Sharpe lift > threshold.
        """
        if not self.is_equity_pipeline_validated:
            return False
        # Net Sharpe lift must clear complexity cost
        return oos_net_sharpe_lift > (complexity_cost_bps / 100.0)
