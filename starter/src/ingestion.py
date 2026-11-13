"""Read and normalize source data. TODO: implement functions."""
import logging
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

logger = logging.getLogger(__name__)


def _chapter_starts(reader: PdfReader) -> list[tuple[int, str, int | None]]:
    """Read top-level PDF bookmarks as (start_page, chapter_title, chapter_number), sorted by page."""
    starts = []
    for item in reader.outline:
        if isinstance(item, list):  # nested list = sub-bookmarks of the previous entry
            continue
        page = reader.get_destination_page_number(item) + 1
        match = re.match(r"Chapter\s+(\d+)\s+(.+)", item.title.strip())
        if match:
            starts.append((page, match.group(2).strip(), int(match.group(1))))
        else:
            starts.append((page, item.title.strip(), None))  # e.g. Preface, Answer Key, Index
    return sorted(starts)


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract every physical page with its 1-based PDF page number, source and chapter.

    All pages are returned, including empty ones, so callers can count and log them;
    metadata["is_empty"] marks pages with no extractable text and metadata["error"]
    records extraction failures. OCR, when needed, is a separate step.
    """
    reader = PdfReader(path)
    chapters = _chapter_starts(reader)
    pages = []
    for index, pdf_page in enumerate(reader.pages):
        page_number = index + 1
        metadata = {"chapter": None, "chapter_number": None}
        for start, title, number in chapters:
            if start <= page_number:
                metadata["chapter"], metadata["chapter_number"] = title, number
        try:
            text = normalize_text(pdf_page.extract_text() or "")
        except Exception as exc:  # keep going; one broken page should not stop ingestion
            text = ""
            metadata["error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("%s page %d: extraction failed: %s", source, page_number, exc)
        metadata["char_count"] = len(text)
        metadata["is_empty"] = not text
        if not text and "error" not in metadata:
            logger.info("%s page %d: no extractable text", source, page_number)
        pages.append(DocumentPage(document_id, source, page_number, text, metadata))
    return pages


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace; keep line and paragraph breaks for chunking."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
