"""Model Doctor: Literature-grounded diagnostic engine for fixing quantitative trading models.

Maps common trading model defects (leakage, overfitting, bad labeling, regime breakdown,
predatory slippage, momentum crashes) to proven mathematical remedies from seminal
trading books and papers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import re
from typing import Any

from edge.rag.pipeline import QuantRAGPipeline

logger = logging.getLogger(__name__)


@dataclass
class ModelDiagnosis:
    symptom: str
    detected_failure_modes: list[str]
    retrieved_passages: list[dict[str, Any]]
    root_cause_analysis: str
    mathematical_remedy: str
    implementation_recipe: str
    literature_citations: list[str]


class ModelDoctor:
    """Specialist engine that queries the quantitative literature to diagnose and fix

    machine learning & algorithmic trading models.
    """

    FAILURE_TAXONOMY = {
        "overfitting_and_data_snooping": {
            "keywords": [
                "overfit",
                "in-sample",
                "out-of-sample",
                "train sharpe",
                "test sharpe",
                "multiple testing",
                "pbo",
                "selection bias",
                "curve fitting",
            ],
            "primary_authors": ["Marcos López de Prado", "David Bailey"],
            "suggested_topics": ["overfitting"],
            "core_concepts": [
                "Deflated Sharpe Ratio (DSR)",
                "Probability of Backtest Overfitting (PBO)",
                "Combinatorial Purged Cross-Validation (CPCV)",
                "Haircut Sharpe Ratio",
            ],
        },
        "leakage_and_cross_validation": {
            "keywords": [
                "leakage",
                "lookahead",
                "serial correlation",
                "cross validation",
                "k-fold",
                "future data",
                "overlapping returns",
            ],
            "primary_authors": ["Marcos López de Prado"],
            "suggested_topics": ["leakage"],
            "core_concepts": [
                "Purged K-Fold Cross-Validation",
                "Embargoing",
                "Sample Uniqueness and Label Overlap",
            ],
        },
        "labeling_and_target_specification": {
            "keywords": [
                "labeling",
                "fixed horizon",
                "win rate",
                "stop loss",
                "profit target",
                "triple barrier",
                "meta labeling",
                "bet sizing",
            ],
            "primary_authors": ["Marcos López de Prado"],
            "suggested_topics": ["labeling"],
            "core_concepts": [
                "Triple-Barrier Method (upper, lower, vertical barriers)",
                "Meta-Labeling (separate classification from bet sizing)",
                "CUSUM Filter for event-driven sampling",
            ],
        },
        "non_stationarity_and_memory": {
            "keywords": [
                "stationarity",
                "unit root",
                "differencing",
                "returns vs price",
                "adf test",
                "memory loss",
                "fractional differentiation",
            ],
            "primary_authors": ["Marcos López de Prado"],
            "suggested_topics": ["feature_engineering"],
            "core_concepts": [
                "Fractionally Differentiated Features (FracDiff d in [0, 1])",
                "Memory Preservation vs Stationarity trade-off",
                "Augmented Dickey-Fuller (ADF) thresholding",
            ],
        },
        "collinear_features_and_importance": {
            "keywords": [
                "feature importance",
                "mdi",
                "mda",
                "collinear",
                "multicollinearity",
                "feature selection",
                "tree importance",
            ],
            "primary_authors": ["Marcos López de Prado"],
            "suggested_topics": ["feature_importance"],
            "core_concepts": [
                "Mean Decrease Impurity (MDI) substitution effects",
                "Mean Decrease Accuracy (MDA) with out-of-sample scoring",
                "Single Feature Importance (SFI)",
                "Clustered Feature Importance",
            ],
        },
        "regime_shift_and_changepoints": {
            "keywords": [
                "regime",
                "changepoint",
                "shift",
                "breakdown",
                "volatility spike",
                "bocpd",
                "run length",
                "hazard rate",
                "market regime",
            ],
            "primary_authors": ["Ryan Prescott Adams", "David J.C. MacKay"],
            "suggested_topics": ["regime_detection"],
            "core_concepts": [
                "Bayesian Online Changepoint Detection (BOCPD)",
                "Recursive Run-Length Posterior P(r_t | x_1:t)",
                "Hazard Function H(tau) = P_gap(g=tau) / sum P_gap",
                "Conjugate-Exponential Likelihood and Sufficient Statistics",
            ],
        },
        "market_impact_and_predatory_trading": {
            "keywords": [
                "market impact",
                "predatory",
                "liquidity crisis",
                "slippage",
                "adverse selection",
                "order execution",
                "temporary impact",
                "permanent impact",
                "racing",
                "fading",
            ],
            "primary_authors": ["Bruce Ian Carlin", "Miguel Sousa Lobo", "S. Viswanathan"],
            "suggested_topics": ["liquidity_market_impact"],
            "core_concepts": [
                "Permanent (gamma) vs Temporary (lambda) price impact",
                "Predatory Racing and Fading differential equilibrium",
                "Surplus loss to distressed trader Delta V_d",
                "Multimarket contagion and liquidity breakdown threshold",
            ],
        },
        "momentum_crashes_and_volatility_scaling": {
            "keywords": [
                "momentum",
                "momentum crash",
                "volatility managed",
                "tsmom",
                "xsmom",
                "drawdown in momentum",
                "rebound crash",
            ],
            "primary_authors": [
                "Kent Daniel",
                "Tobias Moskowitz",
                "Pedro Barroso",
                "Pedro Santa-Clara",
            ],
            "suggested_topics": ["momentum_strategies"],
            "core_concepts": [
                "Volatility-Managed Momentum (Barroso & Santa-Clara)",
                "Dynamic Momentum conditioning on panic states (Daniel & Moskowitz)",
                "Time-Series vs Cross-Sectional Momentum decomposition (Goyal & Jegadeesh)",
            ],
        },
        "volume_price_and_auction_absorption": {
            "keywords": [
                "vpa",
                "volume price",
                "poc",
                "point of control",
                "value area",
                "absorption",
                "climax",
                "false breakout",
                "auction market",
            ],
            "primary_authors": ["Steidlmayer"],
            "suggested_topics": ["volume_price_analysis"],
            "core_concepts": [
                "Volume Price Analysis (effort vs result)",
                "Buying/Selling Climaxes and Absorption Volume",
                "Point of Control (POC) and Value Area High/Low migration",
            ],
        },
    }

    def __init__(self, pipeline: QuantRAGPipeline):
        self.pipeline = pipeline

    def diagnose_model_issue(
        self,
        problem_description: str,
        top_k: int = 5,
        use_llm: bool = True,
    ) -> ModelDiagnosis:
        """Diagnose a model problem by retrieving relevant literature and generating

        an actionable architectural and mathematical fix.
        """
        lower_desc = problem_description.lower()

        # 1. Identify failure modes from taxonomy
        matched_modes = []
        target_topics = []
        for mode_key, config in self.FAILURE_TAXONOMY.items():
            if any(kw in lower_desc for kw in config["keywords"]):
                matched_modes.append(mode_key)
                target_topics.extend(config["suggested_topics"])

        if not matched_modes:
            matched_modes = ["general_quant_model_debugging"]

        # 2. Formulate targeted literature search queries
        search_queries = [problem_description]
        for mode in matched_modes:
            if mode in self.FAILURE_TAXONOMY:
                concepts = self.FAILURE_TAXONOMY[mode]["core_concepts"]
                search_queries.append(" ".join(concepts[:2]))

        # 3. Retrieve relevant literature passages
        retrieved_map: dict[str, dict[str, Any]] = {}
        for q in search_queries[:3]:
            hits = self.pipeline.retrieve(
                query=q,
                top_k=top_k,
                rerank=True,
            )
            for h in hits:
                retrieved_map[h["chunk_id"]] = h

        all_passages = sorted(
            retrieved_map.values(),
            key=lambda x: x.get("rerank_score", x.get("rrf_score", 0)),
            reverse=True,
        )[:top_k]

        # 4. Generate structured diagnosis report
        citations = []
        for p in all_passages:
            cite = (
                f"{p.get('book_author', 'Author')} ({p.get('book_year', 'n.d.')}), "
                f"\"{p.get('book_title')}\", "
                f"Chapter: {p.get('chapter', 'N/A')}, p. {p.get('page_number', '?')}"
            )
            if cite not in citations:
                citations.append(cite)

        # 5. LLM Synthesis or Deterministic Synthesis
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if use_llm and anthropic_key and all_passages:
            try:
                return self._synthesize_with_anthropic(
                    problem_description, matched_modes, all_passages, citations
                )
            except Exception as e:
                logger.warning("Anthropic synthesis failed (%s), falling back to rule-based", e)

        return self._synthesize_rule_based(
            problem_description, matched_modes, all_passages, citations
        )

    def _synthesize_rule_based(
        self,
        problem: str,
        modes: list[str],
        passages: list[dict[str, Any]],
        citations: list[str],
    ) -> ModelDiagnosis:
        """Deterministic, highly technical synthesis grounded directly in the literature."""
        root_causes = []
        math_fixes = []
        code_recipes = []

        if "overfitting_and_data_snooping" in modes:
            root_causes.append(
                "**Backtest Overfitting & Selection Bias**: Standard backtests suffer from selection bias on multiple trials. "
                "The maximum Sharpe ratio discovered across N trials has an inflated expected value that scales as "
                "E[max SR] ~= (1 - gamma_e)*Z^(-1)(1 - 1/N) + gamma_e*Z^(-1)(1 - 1/(N*e)). Without deflating for trial count, "
                "in-sample Sharpe is predominantly selection noise."
            )
            math_fixes.append(
                "**Deflated Sharpe Ratio (DSR)** (López de Prado & Bailey, 2014):\n"
                "$$\\text{DSR} = Z\\left[ \\frac{(\\widehat{\\text{SR}} - \\text{SR}^*) \\sqrt{T-1}}{\\sqrt{1 - \\widehat{\\gamma}_3 \\widehat{\\text{SR}} + \\frac{\\widehat{\\gamma}_4 - 1}{4}\\widehat{\\text{SR}}^2}} \\right]$$\n"
                "where $\\text{SR}^* = \\sqrt{2 \\ln N} + \\dots$ is the expected maximum Sharpe ratio under the null hypothesis across $N$ trials, "
                "and $\\gamma_3, \\gamma_4$ are skewness and kurtosis of returns."
            )
            code_recipes.append(
                "Compute DSR on your strategy returns and reject any signal with DSR < 0.95. "
                "Switch from simple grid search to Combinatorial Purged Cross-Validation (CPCV) to test paths across multiple folds."
            )

        if "leakage_and_cross_validation" in modes:
            root_causes.append(
                "**Information Leakage Across Overlapping Return Horizons**: In financial time series, labels that span multiple bars "
                "introduce substantial serial correlation. Standard k-fold cross-validation randomly assigns overlapping intervals "
                "to train and test sets, causing test labels to leak directly into the training features."
            )
            math_fixes.append(
                "**Purging and Embargoing** (Advances in Financial Machine Learning, Ch 7):\n"
                "1. **Purging**: Remove from training set all observations $i$ whose label evaluation interval $[t_{i,0}, t_{i,1}]$ "
                "overlaps with the test set evaluation interval $[T_0, T_1]$.\n"
                "2. **Embargoing**: Discard training samples immediately following test sets for a window $h$ to eliminate auto-regressive memory."
            )
            code_recipes.append(
                "Implement `PurgedKFold(n_splits=5, pct_embargo=0.01)` where samples with label overlap are explicitly purged "
                "prior to model training."
            )

        if "labeling_and_target_specification" in modes:
            root_causes.append(
                "**Path-Independent Fixed-Horizon Labeling**: Fixed time-horizon labels ($r_{t+h} > 0$) ignore path dynamics: "
                "a trade may hit a ruinous 10% stop-loss intraday before rebounding at day $t+h$. Fixed-horizon models learn false positives "
                "because they ignore the intermediate drawdowns that trigger real broker stop-outs."
            )
            math_fixes.append(
                "**The Triple-Barrier Method** (López de Prado, Ch 3):\n"
                "Define three dynamic barriers for each event: upper barrier (profit take: $P_t (1 + \\text{pt} \\cdot \\sigma_t)$), "
                "lower barrier (stop loss: $P_t (1 - \\text{sl} \\cdot \\sigma_t)$), and vertical barrier (holding limit $t + H$). "
                "Label is the sign of the first barrier touched: $y_i \\in \\{+1, -1, 0\\}$."
            )
            code_recipes.append(
                "Deploy **Meta-Labeling**: Train Model 1 (e.g. Trend/BOCPD) to predict direction (+1/-1). "
                "Train Model 2 (Binary Classifier) to predict whether Model 1's position will hit the profit target before the stop loss. "
                "Size bets proportional to Model 2's predicted probability $P(y=1)$."
            )

        if "non_stationarity_and_memory" in modes:
            root_causes.append(
                "**Loss of Memory via Integer Differencing**: Taking first differences ($d=1$) of prices produces stationary returns, "
                "but completely eliminates memory of structural levels (support, resistance, long-term trends). Raw prices ($d=0$) preserve memory "
                "but have unit roots that cause spurious regression."
            )
            math_fixes.append(
                "**Fractionally Differentiated Features (FracDiff)** (López de Prado, Ch 5):\n"
                "Apply binomial expansion $(1-B)^d = \\sum_{k=0}^\\infty (-1)^k \\binom{d}{k} B^k$ with fractional real $d \\in (0, 1)$. "
                "Find the minimum $d^*$ such that the Augmented Dickey-Fuller (ADF) test p-value $< 0.05$ (typically $d \\approx 0.35 - 0.55$). "
                "This achieves stationarity while preserving $>80\\%$ of price memory correlation."
            )
            code_recipes.append(
                "Compute fractional differentiation weights $w_k = -w_{k-1} \\frac{d - k + 1}{k}$ with weight threshold $\\tau = 10^{-4}$. "
                "Feed $X_t^{(d^*)}$ to tree models rather than raw prices or 1-period percent changes."
            )

        if "regime_shift_and_changepoints" in modes:
            root_causes.append(
                "**Static Parameter Decay During Macro Regime Changes**: Machine learning parameters calibrated in trending or low-volatility "
                "regimes suffer catastrophic failure when volatility or trend persistence shifts. Models require causal, online changepoint estimation."
            )
            math_fixes.append(
                "**Bayesian Online Changepoint Detection (BOCPD)** (Adams & MacKay, 2007):\n"
                "Exact recursive calculation of current run length $r_t$ (time elapsed since last changepoint):\n"
                "$$P(r_t=r_{t-1}+1, x_{1:t}) = P(r_{t-1}, x_{1:t-1}) \\pi_t^{(r)} (1 - H(r_{t-1}))$$\n"
                "$$P(r_t=0, x_{1:t}) = \\sum_{r_{t-1}} P(r_{t-1}, x_{1:t-1}) \\pi_t^{(r)} H(r_{t-1})$$\n"
                "where $\\pi_t^{(r)} = P(x_t | \\nu_t^{(r)}, \\chi_t^{(r)})$ is the exponential-family predictive distribution, and $H(\\tau) = 1/\\lambda$ is the hazard function."
            )
            code_recipes.append(
                "When $P(r_t < 5 | x_{1:t}) > 0.60$, cut strategy position size by $50\\%$ and expand trailing stop distances, "
                "allowing sufficient statistics to adapt to the new regime."
            )

        if "market_impact_and_predatory_trading" in modes:
            root_causes.append(
                "**Predatory Trading and Transient Liquidity Squeeze**: Large orders trigger strategic racing and fading by predatory traders. "
                "In a tight oligopoly, competitors detect distressed order flow, front-run the initial wave (racing), and fade the tail (buying back)."
            )
            math_fixes.append(
                "**Carlin, Lobo, Viswanathan (2007) Equilibrium Pricing Model**:\n"
                "$$P_t = U_t + \\gamma X_t + \\lambda Y_t$$\n"
                "where $\\gamma$ is permanent price impact, $\\lambda$ is temporary price impact, and $Y_t$ is trading rate. "
                "When cooperation breaks down (|\\Delta x| > \\Delta x^*), distressed traders lose surplus "
                "$\\Delta V_d = \\frac{\\gamma}{6} \\left[ \\frac{2e^{\\frac{\\gamma}{\\lambda}T} + e^{\\frac{2\\gamma}{3\\lambda}T} + e^{\\frac{\\gamma}{3\\lambda}T} + 2}{e^{\\frac{\\gamma}{\\lambda}T} - 1} - \\frac{6}{\\frac{\\gamma}{\\lambda}T} \\right] \\Delta x^2$."
            )
            code_recipes.append(
                "Slice execution dynamically over a randomized TWAP/VWAP schedule with horizon $T > \\frac{3\\lambda}{\\gamma} \\ln(1 + \\dots)$, "
                "hiding terminal trading target to avoid triggering the predatory racing threshold."
            )

        if "momentum_crashes_and_volatility_scaling" in modes:
            root_causes.append(
                "**Unmanaged Momentum Crash Risk in Rebound States**: Standard momentum exhibits negative skewness and crashes during "
                "violent bear-market rallies (when distressed loser stocks explode upward). Daniel & Moskowitz (2016) show momentum is an implicit short call option."
            )
            math_fixes.append(
                "**Volatility-Managed Momentum** (Barroso & Santa-Clara, 2015):\n"
                "Scale momentum exposure inversely to predicted realized variance:\n"
                "$$W_{t} = \\frac{\\sigma_{\\text{target}}}{\\widehat{\\sigma}_{t}}$$\n"
                "where $\\widehat{\\sigma}_t^2 = 21 \\sum_{i=0}^{125} w_i r_{t-i}^2$. This nearly doubles the Sharpe ratio and eliminates crash tail risk."
            )
            code_recipes.append(
                "Apply dynamic volatility scaling with target annualized volatility $\\sigma_{\\text{target}} = 12\\%$. "
                "Incorporate Daniel & Moskowitz bear-market rebound indicator to cut short leg allocation after market drops > 20%."
            )

        if not root_causes:
            root_causes.append(
                "Model performance degradation is typically attributable to either (a) feature non-stationarity, "
                "(b) lookahead leakage in cross-validation, (c) flawed labeling, or (d) unmodeled execution costs."
            )
            math_fixes.append(
                "Consult Marcos López de Prado (2018) Chapters 3 (Labeling), 5 (Fractional Differentiation), and 7 (Cross-Validation)."
            )
            code_recipes.append(
                "Run purged cross-validation, apply fractional differentiation, and check deflated Sharpe ratio."
            )

        return ModelDiagnosis(
            symptom=problem,
            detected_failure_modes=modes,
            retrieved_passages=passages,
            root_cause_analysis="\n\n".join(root_causes),
            mathematical_remedy="\n\n".join(math_fixes),
            implementation_recipe="\n\n".join(code_recipes),
            literature_citations=citations,
        )

    def _synthesize_with_anthropic(
        self,
        problem: str,
        modes: list[str],
        passages: list[dict[str, Any]],
        citations: list[str],
    ) -> ModelDiagnosis:
        """Call Anthropic Claude to craft a bespoke diagnostic report using retrieved literature context."""
        import anthropic

        client = anthropic.Anthropic()
        context_str = self.pipeline.format_context(passages, max_chars=8000)

        prompt = f"""You are a World-Class Quantitative Trading Systems Architect and Financial ML Specialist.
A quantitative researcher presents this model failure symptom:
"{problem}"

Detected Failure Modes: {', '.join(modes)}

Below are retrieved excerpts from seminal quantitative literature (López de Prado, Carlin et al., Adams & MacKay, Moskowitz et al.):
{context_str}

Please generate an authoritative, rigorous diagnosis with:
1. ROOT CAUSE ANALYSIS: Explain why this failure happens from statistical, microstructure, and econometric first principles.
2. MATHEMATICAL REMEDY: Provide the exact mathematical formulation (equations, variables, theorems) from the retrieved literature.
3. STEP-BY-STEP CODE/ARCHITECTURE IMPLEMENTATION: Concrete algorithm, parameters, and python implementation steps to fix the model.
4. LITERATURE CITATIONS: Explicitly cite Book Title, Author, Chapter, and Page numbers.
"""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text

        return ModelDiagnosis(
            symptom=problem,
            detected_failure_modes=modes,
            retrieved_passages=passages,
            root_cause_analysis=response_text,
            mathematical_remedy="See literature-grounded diagnosis above.",
            implementation_recipe="Follow prescribed architecture in diagnosis.",
            literature_citations=citations,
        )
