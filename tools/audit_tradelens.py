"""
TradeLens & TradeLens++ CLI Audit Tool.

Loads counterfactual decision ledgers and evaluates system vs agentic viability,
multi-factor alpha decomposition, total cost accounting, and Agent Value Ratio (AVR).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np

# Path setup for direct execution
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from edge.research.counterfactual_ledger import CounterfactualLedger, DecisionRecord
    from edge.eval.tradelens import decompose_tradelens, compute_tradelens_plus_plus
except ImportError:
    from research.counterfactual_ledger import CounterfactualLedger
    from eval.tradelens import decompose_tradelens, compute_tradelens_plus_plus


def audit_ledger(ledger_path: str, horizon: str = "5d") -> int:
    path = Path(ledger_path)
    if not path.exists():
        print(f"Error: Ledger file not found: {ledger_path}")
        return 1

    ledger = CounterfactualLedger(path)
    records = ledger.load_records()

    if not records:
        print(f"No records found in ledger {ledger_path}.")
        return 0

    print("\n=======================================================")
    print("           TRADELENS++ SYSTEM & AGENT AUDIT            ")
    print("=======================================================")
    print(f"Ledger Path: {ledger_path}")
    print(f"Total Decision Records: {len(records)}")
    print(f"Evaluation Horizon: {horizon}")
    print("-------------------------------------------------------\n")

    agent_pnls = []
    counterfactual_pnls = []
    market_pnls = []
    c_llm_list = []
    c_trading_list = []

    outcomes_count = 0
    for r in records:
        c_llm_list.append(r.llm_cost_usd)
        c_trading_list.append(r.execution_cost_usd)

        if horizon in r.horizon_outcomes:
            out = r.horizon_outcomes[horizon]
            agent_pnls.append(out.get("realized_agent_pnl", 0.0))
            counterfactual_pnls.append(out.get("counterfactual_pnl", 0.0))
            market_pnls.append(out.get("market_pnl", 0.0))
            outcomes_count += 1

    print(f"Realized Horizon Outcomes Evaluated: {outcomes_count} / {len(records)}")
    total_llm_cost = sum(c_llm_list)
    total_trading_cost = sum(c_trading_list)
    total_cost = total_llm_cost + total_trading_cost

    print(f"Total LLM Inference Cost:       ${total_llm_cost:.4f}")
    print(f"Total Trading Friction Cost:    ${total_trading_cost:.4f}")
    print(f"Total Cost Accounted:           ${total_cost:.4f}\n")

    if outcomes_count == 0:
        print("Warning: No realized horizon outcomes found yet. Run horizon realization first.")
        return 0

    r_agent = np.array(agent_pnls)
    r_counterfactual = np.array(counterfactual_pnls)
    r_mkt = np.array(market_pnls) if any(market_pnls) else np.zeros_like(r_counterfactual)

    res_tl = decompose_tradelens(
        portfolio_returns=r_agent,
        market_returns=r_mkt,
        baseline_selection_returns=r_counterfactual,
        c_total=total_cost,
        c_dynamic=total_llm_cost,
    )

    res_tlplus = compute_tradelens_plus_plus(
        portfolio_returns=r_agent,
        counterfactual_baseline_returns=r_counterfactual,
        market_returns=r_mkt,
        c_llm=total_llm_cost,
        c_trading=total_trading_cost,
    )

    print("---------------- TRADELENS DECOMPOSITION ----------------")
    print(f"Gross Realized PnL (P_gross):       {res_tl.p_gross:+.4f}")
    print(f"Market Drift PnL (P_market):        {res_tl.p_market:+.4f}")
    print(f"Asset Selection PnL (P_selection):  {res_tl.p_selection:+.4f}")
    print(f"Dynamic Timing PnL (P_timing):      {res_tl.p_timing:+.4f}")
    print(f"System Viability (R_system):        {res_tl.r_system:+.4f} -> {'PASS (Viable)' if res_tl.is_system_viable else 'FAIL (Value Destruction)'}")
    print(f"Agentic Viability (R_agent):       {res_tl.r_agent:+.4f} -> {'PASS (Viable)' if res_tl.is_agent_viable else 'FAIL (Value Destruction)'}")

    print("\n--------------- TRADELENS++ AGENTIC METRICS -------------")
    print(f"Agent Counterfactual Incremental PnL: {res_tlplus.r_agent_counterfactual:+.4f}")
    print(f"Agent Decision Win Rate:            {res_tlplus.agent_win_rate * 100:.1f}%")
    print(f"Counterfactual t-statistic:         {res_tlplus.counterfactual_tstat:+.2f}")
    print(f"Agent Value Ratio (AVR):            {res_tlplus.agent_value_ratio:.2f}")
    print(f"Agent Value Additive Status:        {'APPROVED FOR LIVE' if res_tlplus.is_agent_value_additive else 'REJECTED (AGENT DESTROYS VALUE)'}")
    print("=======================================================\n")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit TradeLens++ evaluation for agentic trading system.")
    parser.add_argument("--ledger", type=str, required=True, help="Path to counterfactual ledger JSON-L file")
    parser.add_argument("--horizon", type=str, default="5d", help="Horizon key to evaluate (e.g. 1d, 5d, 20d)")
    args = parser.parse_args()

    sys.exit(audit_ledger(args.ledger, args.horizon))


if __name__ == "__main__":
    main()
