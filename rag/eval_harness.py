"""Evaluation harness for the Quantitative RAG Pipeline.

Measures Recall@k, Context Precision, Mean Reciprocal Rank (MRR), and Latency
across a golden benchmark of quantitative model debugging and trading literature tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

from edge.rag.pipeline import QuantRAGPipeline

logger = logging.getLogger(__name__)


@dataclass
class EvalTestCase:
    query: str
    target_authors: list[str]
    target_concepts: list[str]
    min_page: int | None = None
    max_page: int | None = None


GOLDEN_BENCHMARK: list[EvalTestCase] = [
    EvalTestCase(
        query="How do I prevent leakage and serial correlation in financial machine learning cross validation?",
        target_authors=["Marcos López de Prado"],
        target_concepts=["purging", "embargo", "cross-validation"],
    ),
    EvalTestCase(
        query="How to correct for multiple testing and backtest overfitting on Sharpe ratios?",
        target_authors=["Marcos López de Prado"],
        target_concepts=["deflated sharpe", "pbo", "overfitting"],
    ),
    EvalTestCase(
        query="What labeling method replaces fixed time horizons by incorporating stop-loss and take-profit barriers?",
        target_authors=["Marcos López de Prado"],
        target_concepts=["triple-barrier", "barrier", "meta-labeling"],
    ),
    EvalTestCase(
        query="How to make non-stationary price series stationary while preserving long-term memory?",
        target_authors=["Marcos López de Prado"],
        target_concepts=["fractional differentiation", "stationarity", "memory"],
    ),
    EvalTestCase(
        query="How does Bayesian Online Changepoint Detection evaluate the run length and hazard function?",
        target_authors=["Ryan Prescott Adams", "David J.C. MacKay"],
        target_concepts=["run length", "hazard function", "bocpd", "changepoint"],
    ),
    EvalTestCase(
        query="What is the differential game equilibrium for predatory trading and permanent versus temporary price impact?",
        target_authors=["Bruce Ian Carlin", "Miguel Sousa Lobo", "S. Viswanathan"],
        target_concepts=["predatory trading", "temporary price impact", "permanent price impact", "racing and fading"],
    ),
    EvalTestCase(
        query="Why do momentum strategies suffer sudden crashes during market rebounds and how does volatility scaling fix them?",
        target_authors=["Pedro Barroso", "Pedro Santa-Clara", "Kent Daniel", "Tobias Moskowitz"],
        target_concepts=["volatility", "momentum crash", "rebound", "scaling"],
    ),
    EvalTestCase(
        query="How does volume price analysis detect institutional accumulation and absorption at key price levels?",
        target_authors=["Steidlmayer"],
        target_concepts=["volume", "absorption", "accumulation", "vpa"],
    ),
    EvalTestCase(
        query="Why does Mean Decrease Impurity MDI fail with correlated features in tree models?",
        target_authors=["Marcos López de Prado"],
        target_concepts=["mean decrease impurity", "mdi", "collinear", "substitution"],
    ),
    EvalTestCase(
        query="What is the algebraic difference between time series momentum and cross sectional momentum?",
        target_authors=["Amit Goyal", "Narasimhan Jegadeesh", "Tobias Moskowitz"],
        target_concepts=["time series momentum", "cross sectional", "market timing"],
    ),
]


class QuantRAGEvaluator:
    """Benchmark test suite evaluating RAG retrieval precision, recall, MRR, and latency."""

    def __init__(self, pipeline: QuantRAGPipeline):
        self.pipeline = pipeline

    def run_benchmark(self, top_k: int = 5) -> dict[str, Any]:
        """Run all golden queries through pipeline and compute metrics."""
        results = []
        latencies_ms = []

        hits_at_1 = 0
        hits_at_3 = 0
        hits_at_k = 0
        reciprocal_ranks = []
        precision_scores = []

        total_cases = len(GOLDEN_BENCHMARK)

        for case in GOLDEN_BENCHMARK:
            t0 = time.perf_counter()
            retrieved = self.pipeline.retrieve(
                query=case.query,
                top_k=top_k,
                rerank=True,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies_ms.append(elapsed_ms)

            # Check match against targets
            first_hit_rank = None
            relevant_chunks_count = 0

            for rank, chunk in enumerate(retrieved, 1):
                content_lower = chunk.get("content", "").lower()
                author_lower = chunk.get("book_author", "").lower()
                title_lower = chunk.get("book_title", "").lower()

                author_match = any(a.lower() in author_lower for a in case.target_authors)
                concept_match = any(c.lower() in content_lower for c in case.target_concepts)

                if author_match or concept_match:
                    relevant_chunks_count += 1
                    if first_hit_rank is None:
                        first_hit_rank = rank

            if first_hit_rank == 1:
                hits_at_1 += 1
            if first_hit_rank is not None and first_hit_rank <= 3:
                hits_at_3 += 1
            if first_hit_rank is not None and first_hit_rank <= top_k:
                hits_at_k += 1

            rr = 1.0 / first_hit_rank if first_hit_rank is not None else 0.0
            reciprocal_ranks.append(rr)

            precision = relevant_chunks_count / max(1, len(retrieved))
            precision_scores.append(precision)

            results.append({
                "query": case.query,
                "first_hit_rank": first_hit_rank,
                "relevant_chunks": relevant_chunks_count,
                "top_chunk_book": retrieved[0].get("book_title") if retrieved else None,
                "top_chunk_author": retrieved[0].get("book_author") if retrieved else None,
                "latency_ms": round(elapsed_ms, 2),
            })

        latencies_ms.sort()
        p50 = latencies_ms[len(latencies_ms) // 2]
        p95 = latencies_ms[int(len(latencies_ms) * 0.95)]

        metrics = {
            "total_test_cases": total_cases,
            "recall_at_1": round(hits_at_1 / total_cases, 4),
            "recall_at_3": round(hits_at_3 / total_cases, 4),
            f"recall_at_{top_k}": round(hits_at_k / total_cases, 4),
            "mean_reciprocal_rank_mrr": round(sum(reciprocal_ranks) / total_cases, 4),
            "average_precision_at_k": round(sum(precision_scores) / total_cases, 4),
            "latency_p50_ms": round(p50, 2),
            "latency_p95_ms": round(p95, 2),
            "details": results,
        }

        return metrics
