"""Unit tests for chunking behavior."""

from app.rag.chunking import TextChunker


def test_chunking_with_overlap() -> None:
    text = " ".join([f"word{i}" for i in range(1, 41)])
    chunker = TextChunker(chunk_size_words=10, chunk_overlap_words=2)

    chunks = chunker.split(text)

    assert len(chunks) == 5
    assert chunks[0].text.split(" ")[-2:] == chunks[1].text.split(" ")[:2]
    assert chunks[-1].order == 4
