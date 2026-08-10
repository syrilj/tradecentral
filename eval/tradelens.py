"""
TradeLens and TradeLens++ Evaluation Framework for Agentic Quantitative Systems.

Implements rigorous PnL decomposition, multi-factor risk attribution (Fama-French 5-Factor + Momentum),
counterfactual alpha attribution, cost accounting, and Agent Value Ratio (AVR).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Union
import numpy as np
import pandas as pd
from scipy import stats


@dataclass(frozen=True)
class TradeLensDecompositionResult:
    """Core TradeLens Return & Cost Decomposition Result."""
    p_gross: float
    p_market: float
    p_selection: float
    p_timing: float
    c_total: float
    c_dynamic: float
    r_system: float
    r_agent: float
    is_system_viable: bool
    is_agent_viable: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "p_gross": self.p_gross,
            "p_market": self.p_market,
            "p_selection": self.p_selection,
            "p_timing": self.p_timing,
            "c_total": self.c_total,
            "c_dynamic": self.c_dynamic,
            "r_system": self.r_system,
            "r_agent": self.r_agent,
            "is_system_viable": self.is_system_viable,
            "is_agent_viable": self.is_agent_viable,
        }


@dataclass(frozen=True)
class TradeLensPlusPlusResult:
    """Extended TradeLens++ Multi-Factor Risk & Counterfactual Alpha Result."""
    # Return Components
    r_gross: float
    r_beta: float
    r_factor: float
    r_selection: float
    r_timing: float
    r_execution: float
    r_agent_counterfactual: float

    # Factor Betas
    beta_mkt: float
    beta_smb: float
    beta_hml: float
    beta_rmw: float
    beta_cma: float
    beta_mom: float

    # Factor-Adjusted Alpha
    factor_alpha: float
    factor_alpha_tstat: float
    factor_r2: float

    # Cost Breakdown
    c_llm: float
    c_trading: float
    c_infrastructure: float
    c_total: float

    # Agent Metrics
    agent_value_ratio: float
    agent_win_rate: float
    counterfactual_tstat: float
    is_agent_value_additive: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "r_gross": self.r_gross,
            "r_beta": self.r_beta,
            "r_factor": self.r_factor,
            "r_selection": self.r_selection,
            "r_timing": self.r_timing,
            "r_execution": self.r_execution,
            "r_agent_counterfactual": self.r_agent_counterfactual,
            "betas": {
                "MKT": self.beta_mkt,
                "SMB": self.beta_smb,
                "HML": self.beta_hml,
                "RMW": self.beta_rmw,
                "CMA": self.beta_cma,
                "MOM": self.beta_mom,
            },
            "factor_alpha": self.factor_alpha,
            "factor_alpha_tstat": self.factor_alpha_tstat,
            "factor_r2": self.factor_r2,
            "costs": {
                "c_llm": self.c_llm,
                "c_trading": self.c_trading,
                "c_infrastructure": self.c_infrastructure,
                "c_total": self.c_total,
            },
            "agent_metrics": {
                "agent_value_ratio": self.agent_value_ratio,
                "agent_win_rate": self.agent_win_rate,
                "counterfactual_tstat": self.counterfactual_tstat,
                "is_agent_value_additive": self.is_agent_value_additive,
            },
        }


def decompose_tradelens(
    portfolio_returns: pd.Series | np.ndarray,
    market_returns: pd.Series | np.ndarray,
    baseline_selection_returns: pd.Series | np.ndarray,
    c_total: float = 0.0,
    c_dynamic: float = 0.0,
) -> TradeLensDecompositionResult:
    """
    Computes standard TradeLens decomposition:
    P_gross = P_market + P_selection + P_timing
    Where:
    - P_market = Sum of market returns (or beta-weighted market returns)
    - P_selection = Baseline static selection returns - P_market
    - P_timing = Realized dynamic portfolio returns - Baseline selection returns
    """
    r_p = np.asarray(portfolio_returns, dtype=float)
    r_m = np.asarray(market_returns, dtype=float)
    r_s = np.asarray(baseline_selection_returns, dtype=float)

    if len(r_p) != len(r_m) or len(r_p) != len(r_s):
        raise ValueError("portfolio_returns, market_returns, and baseline_selection_returns must have identical length")

    p_gross = float(np.sum(r_p))
    p_market = float(np.sum(r_m))
    p_selection = float(np.sum(r_s - r_m))
    p_timing = float(np.sum(r_p - r_s))

    r_system = p_gross - float(c_total)
    r_agent = p_timing - float(c_dynamic)

    return TradeLensDecompositionResult(
        p_gross=p_gross,
        p_market=p_market,
        p_selection=p_selection,
        p_timing=p_timing,
        c_total=float(c_total),
        c_dynamic=float(c_dynamic),
        r_system=r_system,
        r_agent=r_agent,
        is_system_viable=(r_system > 0.0),
        is_agent_viable=(r_agent > 0.0),
    )


def compute_tradelens_plus_plus(
    portfolio_returns: pd.Series | np.ndarray,
    counterfactual_baseline_returns: pd.Series | np.ndarray,
    market_returns: pd.Series | np.ndarray,
    factor_matrix: Optional[pd.DataFrame] = None,
    execution_friction_returns: Optional[pd.Series | np.ndarray] = None,
    c_llm: float = 0.0,
    c_trading: float = 0.0,
    c_infrastructure: float = 0.0,
    rf_rate: float = 0.0,
) -> TradeLensPlusPlusResult:
    """
    Computes TradeLens++ multi-factor risk attribution and counterfactual agent evaluation.

    Decomposition equation:
    R_p = R_beta + R_factor + R_selection + R_timing + R_execution + R_agent + epsilon

    Agent Value Ratio (AVR):
    AVR = (P_agent_assisted - P_non_agent) / (C_llm + C_tools + C_incremental_execution)
    """
    r_p = np.asarray(portfolio_returns, dtype=float)
    r_base = np.asarray(counterfactual_baseline_returns, dtype=float)
    r_m = np.asarray(market_returns, dtype=float)

    n = len(r_p)
    if len(r_base) != n or len(r_m) != n:
        raise ValueError("portfolio_returns, counterfactual_baseline_returns, and market_returns must have identical length")

    r_exec = np.asarray(execution_friction_returns, dtype=float) if execution_friction_returns is not None else np.zeros(n)

    p_gross = float(np.sum(r_p))
    p_base = float(np.sum(r_base))
    p_exec = float(np.sum(r_exec))

    # Incremental return generated by Agent over Pure Quant Baseline
    delta_pnl = r_p - r_base
    r_agent_counterfactual = float(np.sum(delta_pnl))

    # Calculate Agent Win Rate (fraction of decisions where agent outperformed counterfactual)
    nonzero_deltas = delta_pnl[delta_pnl != 0.0]
    agent_win_rate = float(np.mean(nonzero_deltas > 0.0)) if len(nonzero_deltas) > 0 else 0.5

    # Paired t-statistic for agent counterfactual excess return
    if len(delta_pnl) > 1 and np.std(delta_pnl) > 1e-12:
        t_stat, _ = stats.ttest_1samp(delta_pnl, 0.0)
        counterfactual_tstat = float(t_stat)
    else:
        counterfactual_tstat = 0.0

    # Multi-Factor OLS Regression (Fama-French 5-factor + Momentum)
    excess_ret = r_p - rf_rate
    mkt_excess = r_m - rf_rate

    if factor_matrix is not None and not factor_matrix.empty:
        required_factors = ["MKT", "SMB", "HML", "RMW", "CMA", "MOM"]
        for f in required_factors:
            if f not in factor_matrix.columns:
                factor_matrix[f] = 0.0
        X = factor_matrix[required_factors].values
    else:
        # Default simple market beta + dummy 0 factors
        X = np.column_stack([
            mkt_excess,
            np.zeros(n),
            np.zeros(n),
            np.zeros(n),
            np.zeros(n),
            np.zeros(n),
        ])

    X_design = np.column_stack([np.ones(n), X])
    try:
        beta_hat, residuals, rank, s = np.linalg.lstsq(X_design, excess_ret, rcond=None)
        alpha = beta_hat[0]
        betas = beta_hat[1:7]
        y_pred = X_design @ beta_hat
        ss_tot = np.sum((excess_ret - np.mean(excess_ret)) ** 2)
        ss_res = np.sum((excess_ret - y_pred) ** 2)
        r2 = max(0.0, 1.0 - (ss_res / ss_tot)) if ss_tot > 1e-12 else 0.0

        # Alpha t-stat
        if n > 7:
            sigma_sq = ss_res / (n - 7)
            cov_matrix = sigma_sq * np.linalg.pinv(X_design.T @ X_design)
            alpha_se = np.sqrt(max(1e-12, cov_matrix[0, 0]))
            alpha_tstat = float(alpha / alpha_se)
        else:
            alpha_tstat = 0.0
    except np.linalg.LinAlgError:
        alpha = 0.0
        betas = np.zeros(6)
        alpha_tstat = 0.0
        r2 = 0.0

    beta_mkt = float(betas[0])
    beta_smb = float(betas[1])
    beta_hml = float(betas[2])
    beta_rmw = float(betas[3])
    beta_cma = float(betas[4])
    beta_mom = float(betas[5])

    r_beta = float(np.sum(beta_mkt * mkt_excess))
    r_factor = float(np.sum(X[:, 1:] @ betas[1:]))

    r_selection = float(np.sum(r_base - r_m))
    r_timing = float(np.sum(r_p - r_base))

    # Total Costs
    c_total = float(c_llm + c_trading + c_infrastructure)

    # Agent Value Ratio (AVR)
    # AVR = (Realized Agent Incremental Return) / (LLM + Incremental Execution + Tool Costs)
    c_incremental_agent = float(c_llm + c_trading)
    if c_incremental_agent > 1e-8:
        avr = float(r_agent_counterfactual / c_incremental_agent)
    else:
        avr = float('inf') if r_agent_counterfactual > 0 else 0.0

    is_agent_value_additive = bool(r_agent_counterfactual > 0.0 and avr >= 1.0 and counterfactual_tstat > 0.0)

    return TradeLensPlusPlusResult(
        r_gross=p_gross,
        r_beta=r_beta,
        r_factor=r_factor,
        r_selection=r_selection,
        r_timing=r_timing,
        r_execution=p_exec,
        r_agent_counterfactual=r_agent_counterfactual,
        beta_mkt=beta_mkt,
        beta_smb=beta_smb,
        beta_hml=beta_hml,
        beta_rmw=beta_rmw,
        beta_cma=beta_cma,
        beta_mom=beta_mom,
        factor_alpha=float(alpha),
        factor_alpha_tstat=alpha_tstat,
        factor_r2=float(r2),
        c_llm=float(c_llm),
        c_trading=float(c_trading),
        c_infrastructure=float(c_infrastructure),
        c_total=c_total,
        agent_value_ratio=avr,
        agent_win_rate=agent_win_rate,
        counterfactual_tstat=counterfactual_tstat,
        is_agent_value_additive=is_agent_value_additive,
    )
