"""Edge Quantitative RAG System for Trading Books and Research Papers.

Designed for quantitative model fixing, backtest debugging, and microstructure diagnosis.
"""

from edge.rag.chunker import DocumentChunk, HierarchicalChunker
from edge.rag.document_parser import BookParser, ParsedBook, ParsedPage
from edge.rag.embeddings import LocalSentenceEmbeddingEngine
from edge.rag.model_doctor import ModelDoctor
from edge.rag.pipeline import QuantRAGPipeline
from edge.rag.reranker import CrossEncoderReranker
from edge.rag.vector_store import HybridVectorStore

__all__ = [
    "BookParser",
    "CrossEncoderReranker",
    "DocumentChunk",
    "HierarchicalChunker",
    "HybridVectorStore",
    "LocalSentenceEmbeddingEngine",
    "ModelDoctor",
    "ParsedBook",
    "ParsedPage",
    "QuantRAGPipeline",
]
