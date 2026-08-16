"""
Cost Accounting Module for TradeLens & TradeLens++.

Tracks LLM inference costs (tokens, pricing tiers, tool call overhead),
trading execution costs (commissions, spread, slippage, non-linear market impact),
and system infrastructure run-time costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


# Standard LLM Pricing Tiers (per 1,000,000 tokens) in USD as of 2025/2026
MODEL_PRICING_USD_PER_M = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}


@dataclass(frozen=True)
class LLMCostModel:
    """Calculates LLM inference and tool usage costs."""
    model_name: str = "gpt-4o"
    tool_call_cost_usd: float = 0.001

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        num_tool_calls: int = 0,
        custom_input_rate_per_m: Optional[float] = None,
        custom_output_rate_per_m: Optional[float] = None,
    ) -> float:
        """Returns total inference + tool call cost in USD."""
        if custom_input_rate_per_m is not None and custom_output_rate_per_m is not None:
            input_rate = custom_input_rate_per_m
            output_rate = custom_output_rate_per_m
        else:
            model_key = self.model_name.lower().strip()
            pricing = MODEL_PRICING_USD_PER_M.get(model_key, MODEL_PRICING_USD_PER_M["gpt-4o"])
            input_rate = pricing["input"]
            output_rate = pricing["output"]

        input_cost = (prompt_tokens / 1_000_000.0) * input_rate
        output_cost = (completion_tokens / 1_000_000.0) * output_rate
        tools_cost = num_tool_calls * self.tool_call_cost_usd

        return float(input_cost + output_cost + tools_cost)


@dataclass(frozen=True)
class TradingFrictionModel:
    """Execution cost model with fixed bps and non-linear market impact."""
    commission_bps: float = 2.5
    half_spread_bps: float = 2.5
    slippage_bps: float = 2.5
    impact_multiplier_eta: float = 0.5

    def calculate_trade_cost(
        self,
        trade_value_usd: float,
        adv_usd: float,
        daily_volatility: float = 0.02,
    ) -> Dict[str, float]:
        """
        Calculates trade execution costs in USD and basis points:
        Market Impact BPS = eta * volatility_bps * (trade_value / ADV)^1.5
        """
        if trade_value_usd <= 0:
            return {"fixed_bps": 0.0, "impact_bps": 0.0, "total_bps": 0.0, "cost_usd": 0.0}

        fixed_bps = self.commission_bps + self.half_spread_bps + self.slippage_bps
        if adv_usd > 0:
            vol_bps = daily_volatility * 10_000.0
            participation = min(trade_value_usd / adv_usd, 1.0)
            impact_bps = self.impact_multiplier_eta * vol_bps * (participation ** 1.5)
        else:
            impact_bps = 0.0

        total_bps = fixed_bps + impact_bps
        cost_usd = trade_value_usd * (total_bps / 10_000.0)

        return {
            "fixed_bps": float(fixed_bps),
            "impact_bps": float(impact_bps),
            "total_bps": float(total_bps),
            "cost_usd": float(cost_usd),
        }


@dataclass(frozen=True)
class SystemInfrastructureCostModel:
    """Tracks infrastructure, cloud VM, and hosting operational cost."""
    cost_per_hour_usd: float = 0.10  # e.g. standard CPU worker node rate

    def calculate_cost(self, runtime_seconds: float) -> float:
        return float((max(0.0, runtime_seconds) / 3600.0) * self.cost_per_hour_usd)


@dataclass
class TotalDecisionCycleCost:
    """Aggregates all costs incurred during a single agentic trading decision cycle."""
    llm_cost_usd: float = 0.0
    trading_cost_usd: float = 0.0
    infrastructure_cost_usd: float = 0.0

    @property
    def total_cost_usd(self) -> float:
        return self.llm_cost_usd + self.trading_cost_usd + self.infrastructure_cost_usd

    def as_dict(self) -> Dict[str, float]:
        return {
            "llm_cost_usd": self.llm_cost_usd,
            "trading_cost_usd": self.trading_cost_usd,
            "infrastructure_cost_usd": self.infrastructure_cost_usd,
            "total_cost_usd": self.total_cost_usd,
        }
