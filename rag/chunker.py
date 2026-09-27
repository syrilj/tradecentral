"""Hierarchical and structural chunker for quantitative finance books and papers.

Implements header-aware splitting, formula/paragraph boundary preservation,
and automated quantitative topic classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from edge.rag.document_parser import ParsedBook, ParsedPage


@dataclass
class DocumentChunk:
    chunk_id: str
    book_id: str
    book_title: str
    author: str
    chapter: str
    section: str
    page_number: int
    chunk_index: int
    content: str
    token_count: int
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class HierarchicalChunker:
    """Chunks structured books and academic papers while preserving mathematical

    coherence, chapter/section hierarchy, and citation metadata.
    """

    # Domain vocabulary mapping for topic extraction
    TOPIC_KEYWORDS = {
        "overfitting": [
            "overfit",
            "backtest overfitting",
            "deflated sharpe",
            "pbo",
            "multiple testing",
            "data snooping",
            "haircut",
        ],
        "leakage": [
            "leakage",
            "purging",
            "embargo",
            "serial correlation",
            "lookahead",
            "cross-validation",
            "cpcv",
        ],
        "labeling": [
            "triple-barrier",
            "triple barrier",
            "meta-labeling",
            "metalabeling",
            "vertical barrier",
            "stop loss",
            "take profit",
            "cusum",
        ],
        "feature_engineering": [
            "fractional differentiation",
            "fractionally differentiated",
            "stationarity",
            "adf test",
            "memory preservation",
            "order of integration",
        ],
        "feature_importance": [
            "feature importance",
            "mean decrease impurity",
            "mdi",
            "mean decrease accuracy",
            "mda",
            "sfi",
            "single feature importance",
            "collinearity",
            "shap",
        ],
        "regime_detection": [
            "changepoint",
            "bocpd",
            "bayesian online changepoint",
            "hazard function",
            "run length",
            "regime shift",
            "markov switching",
        ],
        "liquidity_market_impact": [
            "predatory trading",
            "market impact",
            "permanent price impact",
            "temporary price impact",
            "episodic illiquidity",
            "racing and fading",
            "liquidity shock",
            "adverse selection",
        ],
        "momentum_strategies": [
            "momentum",
            "tsmom",
            "xsmom",
            "time series momentum",
            "cross sectional momentum",
            "momentum crashes",
            "volatility-managed momentum",
        ],
        "volume_price_analysis": [
            "volume price analysis",
            "vpa",
            "point of control",
            "poc",
            "value area",
            "auction market theory",
            "absorption",
            "accumulation",
            "distribution",
        ],
        "execution_slippage": [
            "execution",
            "slippage",
            "vwap",
            "twap",
            "transaction costs",
            "bid-ask spread",
            "order book",
        ],
    }

    def __init__(
        self,
        chunk_size_chars: int = 2400,  # ~600 tokens
        chunk_overlap_chars: int = 400,  # ~100 tokens
        min_chunk_chars: int = 150,
    ):
        self.chunk_size = chunk_size_chars
        self.chunk_overlap = chunk_overlap_chars
        self.min_chunk_chars = min_chunk_chars

    def chunk_book(self, book: ParsedBook) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        chunk_idx = 0

        # Group pages by chapter to preserve narrative flow
        chapter_pages: dict[str, list[ParsedPage]] = {}
        for p in book.pages:
            chap = p.chapter or "General"
            chapter_pages.setdefault(chap, []).append(p)

        for chapter_name, pages in chapter_pages.items():
            # Combine chapter text while keeping track of page boundary offsets
            full_chapter_text = ""
            char_to_page: list[int] = []

            for page in pages:
                if not page.text.strip():
                    continue
                start_offset = len(full_chapter_text)
                page_text = page.text.strip() + "\n\n"
                full_chapter_text += page_text
                end_offset = len(full_chapter_text)
                char_to_page.extend([page.page_number] * (end_offset - start_offset))

            if not full_chapter_text.strip():
                continue

            # Split chapter text using recursive boundary rules
            raw_splits = self._recursive_split(full_chapter_text)

            current_pos = 0
            for split_text in raw_splits:
                if len(split_text.strip()) < self.min_chunk_chars:
                    current_pos += len(split_text)
                    continue

                # Locate page number for this chunk
                page_idx = min(current_pos, len(char_to_page) - 1) if char_to_page else 1
                page_num = char_to_page[page_idx] if char_to_page else 1

                # Extract section header within split if present
                section = self._extract_section_header(split_text)

                # Detect topics
                topics = self._detect_topics(split_text)

                chunk_id = f"{book.file_hash[:8]}_{chunk_idx:05d}"
                doc_chunk = DocumentChunk(
                    chunk_id=chunk_id,
                    book_id=book.file_hash,
                    book_title=book.title,
                    author=book.author,
                    chapter=chapter_name,
                    section=section,
                    page_number=page_num,
                    chunk_index=chunk_idx,
                    content=split_text.strip(),
                    token_count=max(1, len(split_text) // 4),  # rough token estimate
                    topics=topics,
                    metadata={
                        "year": book.year,
                        "source": book.file_path,
                    },
                )
                chunks.append(doc_chunk)
                chunk_idx += 1
                current_pos += len(split_text) - self.chunk_overlap

        return chunks

    def _recursive_split(self, text: str) -> list[str]:
        """Split text cleanly honoring paragraph breaks, formulas, and sentences."""
        if len(text) <= self.chunk_size:
            return [text]

        splits: list[str] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            if end >= text_len:
                splits.append(text[start:end])
                break

            # Find the best split boundary before `end`
            best_boundary = self._find_best_boundary(text, start, end)
            splits.append(text[start:best_boundary])

            # Advance start with overlap
            start = max(start + 1, best_boundary - self.chunk_overlap)

        return splits

    def _find_best_boundary(self, text: str, start: int, max_end: int) -> int:
        """Prefers section headings, then double newlines, then sentence ends."""
        search_window = text[start + int(self.chunk_size * 0.5) : max_end]
        window_offset = start + int(self.chunk_size * 0.5)

        # 1. Section headers (e.g. ## Heading or 3.2 Heading)
        h_match = list(re.finditer(r"\n(?=#{1,4}\s|\d+\.\d+\s+[A-Z])", search_window))
        if h_match:
            return window_offset + h_match[-1].start()

        # 2. Paragraph breaks (\n\n)
        p_match = list(re.finditer(r"\n\s*\n", search_window))
        if p_match:
            return window_offset + p_match[-1].end()

        # 3. Sentence ends (. ! ?) followed by space or newline
        s_match = list(re.finditer(r"[.!?]\s+", search_window))
        if s_match:
            return window_offset + s_match[-1].end()

        # 4. Single newline
        nl_match = list(re.finditer(r"\n", search_window))
        if nl_match:
            return window_offset + nl_match[-1].end()

        # 5. Space
        space_match = list(re.finditer(r"\s+", search_window))
        if space_match:
            return window_offset + space_match[-1].end()

        # Fallback to max_end
        return max_end

    def _extract_section_header(self, text: str) -> str:
        lines = [l.strip() for l in text.split("\n") if l.strip()][:4]
        for l in lines:
            if re.match(r"^(?:#{1,4}\s+|\d+\.\d+\s+|Section\s+\d+)", l, re.IGNORECASE):
                return l.lstrip("#").strip()
        return ""

    def _detect_topics(self, text: str) -> list[str]:
        lower_text = text.lower()
        matched = []
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            if any(kw in lower_text for kw in keywords):
                matched.append(topic)
        return matched
