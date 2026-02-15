"""Chunking utilities with overlap and metadata retention."""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.normalizer import clean_text


@dataclass(slots=True)
class TextChunk:
    """A single text chunk with local ordering information."""

    text: str
    order: int


class TextChunker:
    """Split text into overlapping word-based chunks."""

    def __init__(self, chunk_size_words: int, chunk_overlap_words: int) -> None:
        if chunk_size_words <= 0:
            raise ValueError("chunk_size_words must be > 0")
        if chunk_overlap_words < 0:
            raise ValueError("chunk_overlap_words must be >= 0")
        if chunk_overlap_words >= chunk_size_words:
            raise ValueError("chunk_overlap_words must be smaller than chunk_size_words")

        self._chunk_size_words = chunk_size_words
        self._chunk_overlap_words = chunk_overlap_words

    def split(self, text: str) -> list[TextChunk]:
        """Return non-empty overlapping chunks."""
        normalized = clean_text(text)
        if not normalized:
            return []

        words = normalized.split(" ")
        chunks: list[TextChunk] = []
        start = 0
        order = 0
        step = self._chunk_size_words - self._chunk_overlap_words

        while start < len(words):
            end = min(start + self._chunk_size_words, len(words))
            chunk_text = " ".join(words[start:end]).strip()
            if chunk_text:
                chunks.append(TextChunk(text=chunk_text, order=order))
                order += 1
            if end == len(words):
                break
            start += step

        return chunks
