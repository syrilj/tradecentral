"""Document parser for trading books and quantitative research papers.

Supports PDF, Markdown, and text formats with Table of Contents (TOC) extraction,
running header/footer cleanup, and chapter/section mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
from typing import Any

try:
    import pypdf
except ImportError:
    pypdf = None


@dataclass
class ParsedPage:
    page_number: int  # 1-indexed
    text: str
    chapter: str = ""
    section: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedBook:
    title: str
    author: str
    year: int | None
    file_path: str
    file_hash: str
    total_pages: int
    chapters: list[dict[str, Any]] = field(default_factory=list)
    pages: list[ParsedPage] = field(default_factory=list)


class BookParser:
    """Robust extractor for dense quantitative books and research papers."""

    # Common author / title heuristic patterns
    KNOWN_TITLES = {
        "Advances in Financial Machine Learning": ("Marcos López de Prado", 2018),
        "Bayesian Online Changepoint Detection": ("Ryan Prescott Adams & David J.C. MacKay", 2007),
        "Episodic Liquidity Crises": ("Bruce Ian Carlin, Miguel Sousa Lobo, S. Viswanathan", 2007),
        "Interpretable Context Methodology": ("Jake Van Clief & David McDermott", 2026),
        "Academic Literature on US Equity Trading Strategies": ("Quantitative Synthesis", 2024),
        "Machine Learning Models in Quantitative Investment": ("Paul Bilokon et al.", 2020),
    }

    def __init__(self):
        pass

    @staticmethod
    def compute_sha256(filepath: str | Path) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def parse(self, filepath: str | Path) -> ParsedBook:
        path = Path(filepath).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._parse_pdf(path)
        elif ext in (".md", ".markdown", ".txt"):
            return self._parse_text_or_markdown(path)
        else:
            raise ValueError(f"Unsupported format: {ext} for {path.name}")

    def _parse_pdf(self, path: Path) -> ParsedBook:
        if pypdf is None:
            raise ImportError(
                "pypdf is required to parse PDF documents. Install with `pip install pypdf`."
            )
        file_hash = self.compute_sha256(path)
        reader = pypdf.PdfReader(str(path))
        total_pages = len(reader.pages)

        # 1. Infer metadata
        title, author, year = self._infer_metadata(path, reader)

        # 2. Extract TOC / bookmarks if present
        chapters = self._extract_bookmarks(reader)

        # 3. Extract and clean pages
        parsed_pages: list[ParsedPage] = []
        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            raw_text = page.extract_text() or ""
            clean_text = self._clean_text(raw_text)

            # Determine chapter from TOC outline mapping
            chapter_name = self._resolve_chapter_for_page(page_num, chapters)

            # Secondary heuristic: check if page starts with "Chapter X" or title
            if not chapter_name:
                chapter_name = self._detect_chapter_header(clean_text)

            parsed_pages.append(
                ParsedPage(
                    page_number=page_num,
                    text=clean_text,
                    chapter=chapter_name,
                    section="",
                    metadata={"source": path.name},
                )
            )

        return ParsedBook(
            title=title,
            author=author,
            year=year,
            file_path=str(path),
            file_hash=file_hash,
            total_pages=total_pages,
            chapters=chapters,
            pages=parsed_pages,
        )

    def _parse_text_or_markdown(self, path: Path) -> ParsedBook:
        file_hash = self.compute_sha256(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")

        # Guess title from first header or filename
        title = path.stem.replace("_", " ").replace("-", " ").title()
        author = "Unknown"
        year = None

        for line in lines[:10]:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Check known titles
        for known, (auth, yr) in self.KNOWN_TITLES.items():
            if known.lower() in title.lower():
                title = known
                author = auth
                year = yr
                break

        # Split into simulated pages / chapters (~3000 chars per page)
        pages: list[ParsedPage] = []
        page_size = 3000
        total_pages = max(1, (len(text) + page_size - 1) // page_size)

        current_chapter = "General"
        for p_idx in range(total_pages):
            chunk = text[p_idx * page_size : (p_idx + 1) * page_size]
            # search for header in chunk
            h_match = re.search(r"^(?:#{1,3})\s+(.*)$", chunk, re.MULTILINE)
            if h_match:
                current_chapter = h_match.group(1).strip()

            pages.append(
                ParsedPage(
                    page_number=p_idx + 1,
                    text=self._clean_text(chunk),
                    chapter=current_chapter,
                    section="",
                    metadata={"source": path.name},
                )
            )

        return ParsedBook(
            title=title,
            author=author,
            year=year,
            file_path=str(path),
            file_hash=file_hash,
            total_pages=total_pages,
            chapters=[{"title": current_chapter, "page": 1}],
            pages=pages,
        )

    def _infer_metadata(
        self, path: Path, reader: pypdf.PdfReader
    ) -> tuple[str, str, int | None]:
        filename = path.stem

        # Extract first page sample to detect actual paper/book title
        first_page_sample = ""
        try:
            if reader.pages:
                first_page_sample = (reader.pages[0].extract_text() or "").lower()
                if len(reader.pages) > 1 and len(first_page_sample) < 300:
                    first_page_sample += " " + (reader.pages[1].extract_text() or "").lower()
        except Exception:
            pass

        # Match against curated known trading literature (by filename OR first page text)
        for known_title, (author, year) in self.KNOWN_TITLES.items():
            if known_title.lower() in filename.lower() or known_title.lower() in first_page_sample:
                return known_title, author, year

        # Read PDF metadata
        pdf_title = ""
        pdf_author = ""
        if reader.metadata:
            pdf_title = str(reader.metadata.get("/Title") or "").strip()
            pdf_author = str(reader.metadata.get("/Author") or "").strip()

        # Fallback to cleaned filename
        title = pdf_title if (pdf_title and len(pdf_title) > 3) else filename
        title = re.sub(r"\(.*?\)|\[.*?\]|_|-", " ", title).strip()
        title = " ".join(title.split())

        author = pdf_author if (pdf_author and len(pdf_author) > 2) else "Quantitative Research"
        year = None

        # Check year in filename or first page
        year_match = re.search(r"(?:19|20)\d{2}", filename) or re.search(r"(?:19|20)\d{2}", first_page_sample)
        if year_match:
            year = int(year_match.group(0))

        return title, author, year


    def _extract_bookmarks(self, reader: pypdf.PdfReader) -> list[dict[str, Any]]:
        """Flatten PDF outline/bookmarks into a list of {title, page} dicts."""
        chapters = []
        try:
            outline = reader.outline
            if not outline:
                return chapters

            def _traverse(items):
                for item in items:
                    if isinstance(item, list):
                        _traverse(item)
                    elif hasattr(item, "title"):
                        page_num = 1
                        try:
                            page_dest = reader.get_destination_page_number(item)
                            if page_dest is not None:
                                page_num = page_dest + 1
                        except Exception:
                            pass
                        chapters.append({"title": item.title.strip(), "page": page_num})

            _traverse(outline)
            chapters.sort(key=lambda x: x["page"])
        except Exception:
            pass
        return chapters

    def _resolve_chapter_for_page(
        self, page_num: int, chapters: list[dict[str, Any]]
    ) -> str:
        if not chapters:
            return ""
        current = ""
        for ch in chapters:
            if ch["page"] <= page_num:
                current = ch["title"]
            else:
                break
        return current

    def _detect_chapter_header(self, text: str) -> str:
        lines = [line.strip() for line in text.split("\n") if line.strip()][:5]
        for line in lines:
            if re.match(
                r"^(?:CHAPTER|SECTION|PART|RULE|RESULT)\s+\d+",
                line,
                re.IGNORECASE,
            ):
                return line
            if len(line) < 60 and line.isupper() and len(line) > 5:
                return line.title()
        return ""

    def _clean_text(self, text: str) -> str:
        """Clean ligature issues, line breaks in sentences, and trailing page noise."""
        if not text:
            return ""

        # Replace common ligatures
        ligatures = {
            "ﬁ": "fi",
            "ﬂ": "fl",
            "ﬀ": "ff",
            "ﬃ": "ffi",
            "ﬄ": "ffl",
            "’": "'",
            "“": '"',
            "”": '"',
            "—": " - ",
            "–": "-",
        }
        for k, v in ligatures.items():
            text = text.replace(k, v)

        # Fix hyphenated words across lines (e.g., "differ-\nentiation" -> "differentiation")
        text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)

        # Replace multiple spaces with a single space
        text = re.sub(r"[ \t]+", " ", text)

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove repetitive header/footer page markers e.g. "Page 123 of 400"
        text = re.sub(
            r"^\s*(?:Page\s+\d+|\d+\s+Advances in Financial Machine Learning|\d+\s+The Journal of Finance)\s*$",
            "",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        return text.strip()
