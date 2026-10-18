from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class TextChunk:
    page_number: int
    text: str
    char_start: int
    char_end: int


def _split_text(text: str, max_chars: int = 1800, overlap: int = 200) -> list[tuple[str, int, int]]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [(normalized, 0, len(normalized))]

    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        chunks.append((normalized[start:end], start, end))
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def parse_pdf(pdf_path: str | Path) -> list[TextChunk]:
    """Extract page-aware text chunks from a PDF."""

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF 文件不存在：{path}")

    chunks: list[TextChunk] = []
    document = pymupdf.open(path)
    try:
        for page_index, page in enumerate(document, start=1):
            page_text = page.get_text("text") or ""
            for text, char_start, char_end in _split_text(page_text):
                chunks.append(
                    TextChunk(
                        page_number=page_index,
                        text=text,
                        char_start=char_start,
                        char_end=char_end,
                    )
                )
    finally:
        document.close()
    return chunks

