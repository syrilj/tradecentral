"""
Point-In-Time (PIT) Universe Selection Engine.

Prevents hindsight and survivorship bias by selecting historical universes
strictly as of decision_ts using point-in-time listing metadata and trailing-only
liquidity metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd


@dataclass(frozen=True)
class InstrumentMaster:
    instrument_id: str           # Permanent internal identifier (e.g. "INST_AAPL_001")
    ticker: str                  # Historical ticker as of effective window
    exchange: str
    listing_date: pd.Timestamp   # Date first listed
    delisting_date: Optional[pd.Timestamp]  # Date delisted (None if currently active)
    effective_from: pd.Timestamp # Window start for this ticker/symbol metadata
    effective_to: pd.Timestamp   # Window end for this ticker/symbol metadata
    sector: str
    industry: str
    share_class: str
    tradable: bool = True


@dataclass
class UniverseConfig:
    min_price: float = 5.0
    min_adv: float = 1_000_000.0  # Trailing 20-day average daily volume in USD
    lookback_days: int = 20
    allowed_sectors: Optional[List[str]] = None


def get_universe(
    symbol_master: List[InstrumentMaster],
    market_data: Dict[str, pd.DataFrame],
    decision_ts: pd.Timestamp,
    config: Optional[UniverseConfig] = None,
) -> List[InstrumentMaster]:
    """
    Selects valid tradable instruments as of decision_ts.
    
    Rules:
    1. listing_date <= decision_ts
    2. delisting_date is None or delisting_date > decision_ts
    3. effective_from <= decision_ts <= effective_to
    4. Trailing price >= min_price (calculated strictly using data available before decision_ts)
    5. Trailing ADV >= min_adv (calculated strictly using data available before decision_ts)
    """
    cfg = config or UniverseConfig()
    if isinstance(decision_ts, str):
        decision_ts = pd.Timestamp(decision_ts)

    selected: List[InstrumentMaster] = []

    for inst in symbol_master:
        # Check listing boundaries
        if inst.listing_date > decision_ts:
            continue
        if inst.delisting_date is not None and inst.delisting_date <= decision_ts:
            continue
        if not (inst.effective_from <= decision_ts <= inst.effective_to):
            continue
        if not inst.tradable:
            continue
        if cfg.allowed_sectors and inst.sector not in cfg.allowed_sectors:
            continue

        # Check trailing liquidity & price if market data is provided for this instrument
        inst_key = inst.ticker if inst.ticker in market_data else inst.instrument_id
        if inst_key in market_data:
            df = market_data[inst_key]
            date_col = "timestamps" if "timestamps" in df.columns else "date"
            
            # Trailing window STRICTLY prior to decision_ts (available_ts <= decision_ts)
            hist = df[df[date_col] <= decision_ts]
            if len(hist) < cfg.lookback_days:
                continue
            
            recent_hist = hist.tail(cfg.lookback_days)
            close_col = "close" if "close" in recent_hist.columns else "Price"
            vol_col = "volume" if "volume" in recent_hist.columns else "Volume"

            last_price = float(recent_hist[close_col].iloc[-1])
            adv = float((recent_hist[close_col] * recent_hist[vol_col]).mean())

            if last_price < cfg.min_price or adv < cfg.min_adv:
                continue

        selected.append(inst)

    return selected
