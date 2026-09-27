"""End-to-end Quantitative RAG Pipeline.

Orchestrates multi-book ingestion, hierarchical chunking, hybrid retrieval (dense + BM25),
cross-encoder re-ranking, and context formatting for model diagnosis.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any

from edge.rag.chunker import HierarchicalChunker
from edge.rag.document_parser import BookParser
from edge.rag.embeddings import LocalSentenceEmbeddingEngine
from edge.rag.reranker import CrossEncoderReranker
from edge.rag.vector_store import HybridVectorStore

logger = logging.getLogger(__name__)


class QuantRAGPipeline:
    """Production RAG pipeline engineered for financial books, papers, and quant model diagnosis."""

    def __init__(
        self,
        db_path: str | Path = "data/rag/quant_books.db",
        embedding_model: str = "all-MiniLM-L6-v2",
        reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        enable_reranker: bool = True,
    ):
        self.parser = BookParser()
        self.chunker = HierarchicalChunker()
        self.embed_engine = LocalSentenceEmbeddingEngine(model_name=embedding_model)
        self.vector_store = HybridVectorStore(
            db_path=db_path,
            dimension=self.embed_engine.dimension,
        )
        self.enable_reranker = enable_reranker
        self._reranker: CrossEncoderReranker | None = None
        self._reranker_model_name = reranker_model

    @property
    def reranker(self) -> CrossEncoderReranker:
        if self._reranker is None:
            self._reranker = CrossEncoderReranker(model_name=self._reranker_model_name)
        return self._reranker

    def ingest_file(
        self, filepath: str | Path, force: bool = False
    ) -> dict[str, Any]:
        """Ingest a single book or paper file into the RAG index."""
        path = Path(filepath).resolve()
        start_time = time.time()

        file_hash = self.parser.compute_sha256(path)
        if not force and self.vector_store.is_book_indexed(file_hash):
            logger.info("Book '%s' already indexed (hash=%s). Skipping.", path.name, file_hash[:8])
            return {
                "file": path.name,
                "status": "already_indexed",
                "elapsed_sec": round(time.time() - start_time, 2),
            }

        logger.info("Parsing book: %s", path.name)
        parsed_book = self.parser.parse(path)

        logger.info("Chunking %s (%d pages)", parsed_book.title, parsed_book.total_pages)
        chunks = self.chunker.chunk_book(parsed_book)

        if not chunks:
            logger.warning("No chunks generated for %s", path.name)
            return {"file": path.name, "status": "empty", "chunks": 0}

        logger.info(
            "Embedding %d chunks for '%s'...",
            len(chunks),
            parsed_book.title,
        )
        chunk_texts = [c.content for c in chunks]
        embeddings = self.embed_engine.embed_texts(chunk_texts, show_progress_bar=False)

        logger.info("Upserting into hybrid vector store...")
        self.vector_store.upsert_book(parsed_book, chunks, embeddings)

        elapsed = time.time() - start_time
        logger.info(
            "Ingestion complete for '%s': %d chunks in %.2fs",
            parsed_book.title,
            len(chunks),
            elapsed,
        )

        return {
            "file": path.name,
            "title": parsed_book.title,
            "author": parsed_book.author,
            "total_pages": parsed_book.total_pages,
            "total_chunks": len(chunks),
            "status": "indexed",
            "elapsed_sec": round(elapsed, 2),
        }

    def ingest_directory(
        self, dir_path: str | Path, recursive: bool = True, force: bool = False
    ) -> list[dict[str, Any]]:
        """Ingest all supported books and papers (.pdf, .md, .txt) in a directory."""
        path = Path(dir_path).resolve()
        if not path.is_dir():
            raise NotADirectoryError(f"Directory not found: {path}")

        extensions = ("*.pdf", "*.md", "*.txt")
        files: list[Path] = []
        for ext in extensions:
            if recursive:
                files.extend(path.rglob(ext))
            else:
                files.extend(path.glob(ext))

        # Filter out hidden or cache files
        files = [
            f for f in files
            if not f.name.startswith(".") and "node_modules" not in str(f) and ".venv" not in str(f)
        ]

        logger.info("Found %d candidate documents in %s", len(files), path)
        results = []
        for file in files:
            try:
                res = self.ingest_file(file, force=force)
                results.append(res)
            except Exception as e:
                logger.error("Error ingesting %s: %s", file.name, e)
                results.append({"file": file.name, "status": "error", "error": str(e)})

        return results

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        alpha: float = 0.65,  # 0.65 dense, 0.35 BM25
        rerank: bool | None = None,
        topic_filter: str | None = None,
        book_id_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve the most relevant passages using hybrid search + cross-encoder reranking."""
        if rerank is None:
            rerank = self.enable_reranker

        q_vec = self.embed_engine.embed_query(query)

        # Retrieve top 3x candidates with hybrid search
        candidates_k = top_k * 3 if rerank else top_k
        candidates = self.vector_store.hybrid_search(
            query=query,
            query_embedding=q_vec,
            top_k=candidates_k,
            alpha=alpha,
            topic_filter=topic_filter,
            book_id_filter=book_id_filter,
        )

        if not candidates:
            return []

        if rerank and self.enable_reranker:
            return self.reranker.rerank(query=query, candidates=candidates, top_n=top_k)

        return candidates[:top_k]

    def format_context(
        self, chunks: list[dict[str, Any]], max_chars: int = 12000
    ) -> str:
        """Format retrieved chunks into clean markdown context with strict citation provenance."""
        if not chunks:
            return "No relevant literature retrieved."

        formatted_pieces = []
        total_len = 0

        for idx, c in enumerate(chunks, 1):
            title = c.get("book_title", "Unknown Book")
            author = c.get("book_author", "Unknown Author")
            year = c.get("book_year")
            year_str = f" ({year})" if year else ""
            chapter = c.get("chapter") or "General"
            page = c.get("page_number", "?")
            content = c.get("content", "").strip()

            header = (
                f"### [Passage {idx}] {title}{year_str}\n"
                f"- **Author(s)**: {author}\n"
                f"- **Chapter/Section**: {chapter}\n"
                f"- **Page**: {page}\n"
            )
            block = f"{header}\n```text\n{content}\n```\n"

            if total_len + len(block) > max_chars:
                break

            formatted_pieces.append(block)
            total_len += len(block)

        return "\n".join(formatted_pieces)

    def stats(self) -> dict[str, Any]:
        """Return index statistics."""
        return self.vector_store.get_stats()
