"""Cross-encoder re-ranking module for precision-critical quantitative queries.

Re-scores top candidate chunks from hybrid retrieval, enforcing a score threshold
so that irrelevant chunks are dropped rather than fed to the LLM.
"""

from __future__ import annotations

import logging
from typing import Any
import torch

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Post-retrieval quality gate using cross-encoder scoring."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        min_score: float = -6.0,
        device: str | None = None,
    ):
        self.model_name = model_name
        self.min_score = min_score

        if device is None:
            if torch.backends.mps.is_available():
                self.device = "mps"
            elif torch.cuda.is_available():
                self.device = "cuda"
            else:
                self.device = "cpu"
        else:
            self.device = device

        logger.info(
            "Initializing CrossEncoder model=%s on device=%s",
            self.model_name,
            self.device,
        )

        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(self.model_name, device=self.device)

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Re-rank candidate chunks by cross-encoder relevance score."""
        if not candidates:
            return []

        pairs = [(query, c["content"]) for c in candidates]
        try:
            scores = self.model.predict(pairs)
        except Exception as e:
            logger.warning("Reranking failed (%s); returning original candidates", e)
            return candidates[:top_n]

        scored_candidates = []
        for cand, score in zip(candidates, scores):
            cand_copy = dict(cand)
            cand_copy["rerank_score"] = float(score)
            scored_candidates.append(cand_copy)

        # Sort descending
        scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

        # Apply score threshold filter
        filtered = [c for c in scored_candidates if c["rerank_score"] >= self.min_score]

        # If threshold filtered everything out, keep top 1 to avoid empty context
        if not filtered and scored_candidates:
            filtered = [scored_candidates[0]]

        return filtered[:top_n]
