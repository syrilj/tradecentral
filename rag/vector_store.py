"""Hybrid Vector and FTS5 Store for Quantitative Books and Papers.

Combines SQLite FTS5 (BM25 keyword search) with FAISS / NumPy dense cosine similarity
via Reciprocal Rank Fusion (RRF). Zero external service dependencies.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any
import faiss
import numpy as np

from edge.rag.chunker import DocumentChunk
from edge.rag.document_parser import ParsedBook

logger = logging.getLogger(__name__)


class HybridVectorStore:
    """Production local hybrid store with SQLite FTS5 and FAISS dense vector index."""

    def __init__(
        self,
        db_path: str | Path = "data/rag/quant_books.db",
        faiss_path: str | Path = "data/rag/faiss_index.bin",
        vectors_path: str | Path = "data/rag/embeddings.npy",
        mapping_path: str | Path = "data/rag/chunk_mapping.json",
        dimension: int = 384,
    ):
        self.db_path = Path(db_path)
        self.faiss_path = Path(faiss_path)
        self.vectors_path = Path(vectors_path)
        self.mapping_path = Path(mapping_path)
        self.dimension = dimension

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_sqlite()
        self._load_vector_index()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        """Create relational tables and FTS5 full text search virtual table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS books (
                    book_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL,
                    year INTEGER,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    total_pages INTEGER NOT NULL,
                    total_chunks INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    book_id TEXT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    page_number INTEGER NOT NULL,
                    chapter TEXT,
                    section TEXT,
                    content TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    topics TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_book_id ON chunks(book_id);
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(page_number);
            """
            )

            # SQLite FTS5 Full-Text Search Virtual Table
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    content,
                    chapter,
                    section,
                    book_title,
                    author,
                    topics,
                    tokenize = 'porter unicode61'
                );
            """
            )
            conn.commit()

    def _load_vector_index(self) -> None:
        """Load vector embeddings and chunk ID mapping."""
        self.chunk_ids: list[str] = []
        self.vectors: np.ndarray | None = None

        if self.mapping_path.exists():
            try:
                with open(self.mapping_path, "r", encoding="utf-8") as f:
                    self.chunk_ids = json.load(f)
            except Exception as e:
                logger.warning("Failed to load chunk mapping: %s", e)
                self.chunk_ids = []

        if self.vectors_path.exists() and self.chunk_ids:
            try:
                self.vectors = np.load(str(self.vectors_path))
                if len(self.vectors) != len(self.chunk_ids):
                    logger.warning("Vector length mismatch with chunk mapping, resetting vectors")
                    self.vectors = None
                    self.chunk_ids = []
                else:
                    logger.info("Loaded %d dense vector embeddings from disk", len(self.vectors))
            except Exception as e:
                logger.warning("Failed to load vectors: %s", e)
                self.vectors = None

    def is_book_indexed(self, file_hash: str) -> bool:
        """Check if a book with this content hash is already indexed."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM books WHERE file_hash = ? LIMIT 1;", (file_hash,)
            )
            return cur.fetchone() is not None

    def upsert_book(
        self,
        book: ParsedBook,
        chunks: list[DocumentChunk],
        embeddings: np.ndarray,
    ) -> None:
        """Upsert a book, its chunks, FTS5 tokens, and vector embeddings."""
        if not chunks:
            return

        with self._get_connection() as conn:
            cur = conn.cursor()

            # Remove previous book records if re-indexing
            cur.execute(
                "DELETE FROM books WHERE file_hash = ?;", (book.file_hash,)
            )
            cur.execute(
                "DELETE FROM chunks WHERE book_id = ?;", (book.file_hash,)
            )

            # Insert book record
            cur.execute(
                """
                INSERT INTO books (book_id, title, author, year, file_path, file_hash, total_pages, total_chunks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
                (
                    book.file_hash,
                    book.title,
                    book.author,
                    book.year,
                    book.file_path,
                    book.file_hash,
                    book.total_pages,
                    len(chunks),
                ),
            )

            # Insert chunks & FTS5
            chunk_rows = []
            fts_rows = []
            for c in chunks:
                topics_str = ",".join(c.topics)
                meta_json = json.dumps(c.metadata)
                chunk_rows.append(
                    (
                        c.chunk_id,
                        c.book_id,
                        c.chunk_index,
                        c.page_number,
                        c.chapter,
                        c.section,
                        c.content,
                        c.token_count,
                        topics_str,
                        meta_json,
                    )
                )
                fts_rows.append(
                    (
                        c.chunk_id,
                        c.content,
                        c.chapter,
                        c.section,
                        c.book_title,
                        c.author,
                        topics_str,
                    )
                )

            cur.executemany(
                """
                INSERT INTO chunks (chunk_id, book_id, chunk_index, page_number, chapter, section, content, token_count, topics, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
                chunk_rows,
            )

            cur.executemany(
                """
                INSERT INTO chunks_fts (chunk_id, content, chapter, section, book_title, author, topics)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
                fts_rows,
            )

            conn.commit()

        # Update vector store
        if embeddings is not None and embeddings.shape[0] > 0:
            norm_embs = np.ascontiguousarray(embeddings, dtype=np.float32)
            norms = np.linalg.norm(norm_embs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            norm_embs = norm_embs / norms

            if self.vectors is not None and len(self.vectors) > 0:
                self.vectors = np.vstack([self.vectors, norm_embs])
            else:
                self.vectors = norm_embs

            for c in chunks:
                self.chunk_ids.append(c.chunk_id)

            # Persist vectors and mapping
            np.save(str(self.vectors_path), self.vectors)
            with open(self.mapping_path, "w", encoding="utf-8") as f:
                json.dump(self.chunk_ids, f)

        logger.info(
            "Successfully indexed book '%s' with %d chunks",
            book.title,
            len(chunks),
        )

    def search_dense(
        self, query_embedding: np.ndarray, top_k: int = 20
    ) -> list[tuple[str, float]]:
        """Dense similarity search using normalized matrix dot product."""
        if self.vectors is None or len(self.vectors) == 0 or not self.chunk_ids:
            return []

        q_emb = np.ascontiguousarray(query_embedding, dtype=np.float32).flatten()
        norm = np.linalg.norm(q_emb)
        if norm > 0:
            q_emb = q_emb / norm

        scores = np.dot(self.vectors, q_emb)
        k = min(top_k, len(scores))
        if k <= 0:
            return []

        top_indices = np.argpartition(scores, -k)[-k:]
        sorted_indices = top_indices[np.argsort(-scores[top_indices])]

        results: list[tuple[str, float]] = []
        for idx in sorted_indices:
            if 0 <= idx < len(self.chunk_ids):
                results.append((self.chunk_ids[idx], float(scores[idx])))
        return results


    def search_sparse(
        self, query: str, top_k: int = 20
    ) -> list[tuple[str, float]]:
        """Sparse lexical search using SQLite FTS5 BM25."""
        sanitized_and, sanitized_or = re_clean_fts_query(query)
        if not sanitized_and:
            return []

        with self._get_connection() as conn:
            cur = conn.cursor()
            # Try AND first for high precision
            try:
                cur.execute(
                    """
                    SELECT chunk_id, bm25(chunks_fts, 5.0, 1.0, 2.0, 2.0, 1.0, 3.0) as rank
                    FROM chunks_fts
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank ASC
                    LIMIT ?;
                """,
                    (sanitized_and, top_k),
                )
                rows = cur.fetchall()
                if rows:
                    return [(row["chunk_id"], float(row["rank"])) for row in rows]
            except sqlite3.OperationalError as e:
                logger.debug("FTS AND query failed: %s", e)

            # Fall back to OR query for broader recall
            try:
                cur.execute(
                    """
                    SELECT chunk_id, bm25(chunks_fts, 5.0, 1.0, 2.0, 2.0, 1.0, 3.0) as rank
                    FROM chunks_fts
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank ASC
                    LIMIT ?;
                """,
                    (sanitized_or, top_k),
                )
                rows = cur.fetchall()
                return [(row["chunk_id"], float(row["rank"])) for row in rows]
            except sqlite3.OperationalError as e:
                logger.warning("FTS OR query failed for '%s': %s", query, e)
                return []

    def hybrid_search(
        self,
        query: str,
        query_embedding: np.ndarray,
        top_k: int = 10,
        alpha: float = 0.65,  # 0.65 dense semantic, 0.35 sparse BM25
        topic_filter: str | None = None,
        book_id_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion (RRF) combining dense vector search and sparse BM25."""
        dense_results = self.search_dense(query_embedding, top_k=top_k * 3)
        sparse_results = self.search_sparse(query, top_k=top_k * 3)

        # Dense rank map: chunk_id -> rank (1-indexed)
        dense_ranks = {cid: rank + 1 for rank, (cid, _) in enumerate(dense_results)}
        dense_scores = {cid: score for cid, score in dense_results}

        # Sparse rank map: chunk_id -> rank (1-indexed)
        sparse_ranks = {cid: rank + 1 for rank, (cid, _) in enumerate(sparse_results)}
        sparse_scores = {cid: score for cid, score in sparse_results}

        all_candidate_ids = set(dense_ranks.keys()) | set(sparse_ranks.keys())
        if not all_candidate_ids:
            return []

        # Calculate Reciprocal Rank Fusion (RRF) score
        # RRF_score = alpha * (1 / (60 + dense_rank)) + (1 - alpha) * (1 / (60 + sparse_rank))
        k_const = 60.0
        fused_scores: list[tuple[str, float]] = []

        for cid in all_candidate_ids:
            d_rank = dense_ranks.get(cid, 999)
            s_rank = sparse_ranks.get(cid, 999)

            d_comp = 1.0 / (k_const + d_rank) if cid in dense_ranks else 0.0
            s_comp = 1.0 / (k_const + s_rank) if cid in sparse_ranks else 0.0

            rrf = (alpha * d_comp) + ((1.0 - alpha) * s_comp)
            fused_scores.append((cid, rrf))

        # Sort descending by fused score
        fused_scores.sort(key=lambda x: x[1], reverse=True)

        # Retrieve chunk metadata from SQLite with optional filtering
        candidate_ids = [cid for cid, _ in fused_scores[: top_k * 2]]
        if not candidate_ids:
            return []

        placeholders = ",".join("?" for _ in candidate_ids)
        query_sql = f"""
            SELECT c.chunk_id, c.book_id, c.chunk_index, c.page_number, c.chapter, c.section,
                   c.content, c.token_count, c.topics, c.metadata_json,
                   b.title as book_title, b.author as book_author, b.year as book_year
            FROM chunks c
            JOIN books b ON c.book_id = b.book_id
            WHERE c.chunk_id IN ({placeholders})
        """
        params: list[Any] = list(candidate_ids)

        if topic_filter:
            query_sql += " AND c.topics LIKE ?"
            params.append(f"%{topic_filter}%")

        if book_id_filter:
            query_sql += " AND c.book_id = ?"
            params.append(book_id_filter)

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query_sql, params)
            rows = {row["chunk_id"]: dict(row) for row in cur.fetchall()}

        final_results = []
        for cid, rrf_score in fused_scores:
            if cid in rows:
                item = rows[cid]
                item["rrf_score"] = rrf_score
                item["dense_score"] = dense_scores.get(cid, 0.0)
                item["sparse_score"] = sparse_scores.get(cid, 0.0)
                final_results.append(item)
                if len(final_results) >= top_k:
                    break

        return final_results

    def get_stats(self) -> dict[str, Any]:
        """Return store summary stats."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM books;")
            book_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*), SUM(token_count) FROM chunks;")
            row = cur.fetchone()
            chunk_count = row[0] or 0
            total_tokens = row[1] or 0

            cur.execute(
                "SELECT title, author, total_pages, total_chunks FROM books ORDER BY title;"
            )
            books_list = [dict(r) for r in cur.fetchall()]

        return {
            "total_books": book_count,
            "total_chunks": chunk_count,
            "total_tokens": total_tokens,
            "vector_index_size": len(self.vectors) if self.vectors is not None else 0,
            "books": books_list,
        }



def re_clean_fts_query(query: str) -> tuple[str, str]:
    """Clean and safely quote query tokens for SQLite FTS5 syntax safety.

    Returns (and_query, or_query).
    """
    words = re.findall(r"[A-Za-z0-9]+", query)
    fts_words = [
        f'"{w}"'
        for w in words
        if w.upper() not in ("AND", "OR", "NOT", "NEAR") and len(w) > 1
    ]
    if not fts_words:
        return "", ""
    return " AND ".join(fts_words), " OR ".join(fts_words)
