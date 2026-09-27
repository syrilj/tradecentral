"""Unit tests for the Quantitative Trading RAG Pipeline and Model Doctor."""

from pathlib import Path
import tempfile
import numpy as np
import pytest

from edge.rag.chunker import HierarchicalChunker
from edge.rag.document_parser import BookParser, ParsedBook, ParsedPage
from edge.rag.model_doctor import ModelDoctor
from edge.rag.pipeline import QuantRAGPipeline
from edge.rag.vector_store import HybridVectorStore


@pytest.fixture
def sample_parsed_book() -> ParsedBook:
    pages = [
        ParsedPage(
            page_number=1,
            text=(
                "# Chapter 7: Cross-Validation in Finance\n\n"
                "Standard k-fold cross-validation fails in finance because of serial correlation and overlapping returns. "
                "Purged k-fold cross-validation removes all training samples whose labels overlap with the test set evaluation window. "
                "Embargoing further drops observations immediately after the test split."
            ),
            chapter="Chapter 7: Cross-Validation in Finance",
            section="7.1 Purging and Embargoing",
        ),
        ParsedPage(
            page_number=2,
            text=(
                "# Chapter 3: Target Labeling and the Triple-Barrier Method\n\n"
                "The triple-barrier method sets three barriers: an upper profit-taking barrier, a lower stop-loss barrier, "
                "and a vertical time barrier. In addition, meta-labeling trains a secondary classifier to predict whether "
                "the primary model's bet will be profitable, decoupling direction from bet sizing."
            ),
            chapter="Chapter 3: Target Labeling",
            section="3.2 The Triple-Barrier Method",
        ),
        ParsedPage(
            page_number=3,
            text=(
                "# Bayesian Online Changepoint Detection\n\n"
                "Bayesian Online Changepoint Detection (BOCPD) infers the run length r_t since the most recent changepoint. "
                "The hazard function H(tau) controls the prior probability of a changepoint occurring at interval tau."
            ),
            chapter="BOCPD Foundations",
            section="Run Length Estimation",
        ),
    ]

    return ParsedBook(
        title="Advances in Financial Machine Learning",
        author="Marcos López de Prado",
        year=2018,
        file_path="/mock/path/advances_in_financial_ml.pdf",
        file_hash="mockhash123456",
        total_pages=3,
        chapters=[
            {"title": "Chapter 7: Cross-Validation in Finance", "page": 1},
            {"title": "Chapter 3: Target Labeling", "page": 2},
        ],
        pages=pages,
    )


def test_hierarchical_chunker(sample_parsed_book):
    chunker = HierarchicalChunker(chunk_size_chars=400, chunk_overlap_chars=50)
    chunks = chunker.chunk_book(sample_parsed_book)

    assert len(chunks) >= 3
    # Check that topics are tagged
    all_topics = [t for c in chunks for t in c.topics]
    assert "leakage" in all_topics or "labeling" in all_topics or "regime_detection" in all_topics

    # Check citation metadata
    first_chunk = chunks[0]
    assert first_chunk.book_title == "Advances in Financial Machine Learning"
    assert first_chunk.author == "Marcos López de Prado"
    assert first_chunk.page_number in (1, 2, 3)


def test_hybrid_vector_store(sample_parsed_book):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_quant.db"
        faiss_path = Path(tmpdir) / "test_faiss.bin"
        vectors_path = Path(tmpdir) / "test_vecs.npy"
        mapping_path = Path(tmpdir) / "test_map.json"

        store = HybridVectorStore(
            db_path=db_path,
            faiss_path=faiss_path,
            vectors_path=vectors_path,
            mapping_path=mapping_path,
            dimension=16,
        )

        chunker = HierarchicalChunker()
        chunks = chunker.chunk_book(sample_parsed_book)

        # Generate mock embeddings
        np.random.seed(42)
        mock_embeddings = np.random.randn(len(chunks), 16).astype(np.float32)

        store.upsert_book(sample_parsed_book, chunks, mock_embeddings)

        stats = store.get_stats()
        assert stats["total_books"] == 1
        assert stats["total_chunks"] == len(chunks)

        # Test BM25 sparse search
        sparse_hits = store.search_sparse("purged k-fold", top_k=3)
        assert len(sparse_hits) > 0

        # Test dense search
        query_vec = mock_embeddings[0]
        dense_hits = store.search_dense(query_vec, top_k=3)
        assert len(dense_hits) > 0

        # Test hybrid search
        hybrid_hits = store.hybrid_search("triple-barrier", query_vec, top_k=2)
        assert len(hybrid_hits) > 0
        assert "book_title" in hybrid_hits[0]


@pytest.mark.needs_live_network(
    reason="SentenceTransformer downloads all-MiniLM-L6-v2 from remote hub over network"
)
def test_model_doctor_diagnosis(sample_parsed_book):
    pytest.importorskip(
        "sentence_transformers",
        reason="sentence_transformers required for live embedding engine",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_quant.db"
        pipeline = QuantRAGPipeline(
            db_path=db_path,
            enable_reranker=False,  # Skip reranker in fast unit test
        )

        chunker = HierarchicalChunker()
        chunks = chunker.chunk_book(sample_parsed_book)
        embeddings = pipeline.embed_engine.embed_texts([c.content for c in chunks])
        pipeline.vector_store.upsert_book(sample_parsed_book, chunks, embeddings)

        doctor = ModelDoctor(pipeline)
        diag = doctor.diagnose_model_issue(
            problem_description="My model has lookahead leakage during cross validation",
            top_k=2,
            use_llm=False,
        )

        assert "leakage_and_cross_validation" in diag.detected_failure_modes
        assert "Purged" in diag.root_cause_analysis or "Leakage" in diag.root_cause_analysis
        assert len(diag.literature_citations) > 0
