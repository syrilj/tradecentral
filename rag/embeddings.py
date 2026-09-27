"""Embedding engine for quantitative trading documents.

Supports local SentenceTransformer accelerated by Apple Silicon MPS,
with batching, vector normalization, and caching.
"""

from __future__ import annotations

import logging
from typing import Any
import numpy as np
import torch

logger = logging.getLogger(__name__)


class LocalSentenceEmbeddingEngine:
    """High-speed local dense embedding engine using SentenceTransformers on Apple Silicon / CUDA / CPU."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        batch_size: int = 64,
        device: str | None = None,
    ):
        self.model_name = model_name
        self.batch_size = batch_size

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
            "Initializing embedding engine model=%s on device=%s",
            self.model_name,
            self.device,
        )

        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(self.model_name, device=self.device)
        self.dimension = self.model.get_sentence_embedding_dimension()

    def embed_texts(
        self, texts: list[str], show_progress_bar: bool = False
    ) -> np.ndarray:
        """Embed a list of text strings into normalized float32 numpy vectors."""
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=show_progress_bar,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embeddings.astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single search query."""
        vec = self.embed_texts([query], show_progress_bar=False)
        return vec[0]
