"""Document ingestion pipeline: parse -> chunk -> metadata enrichment."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.core.constants import UTC_TIMEZONE
from app.ingestion.normalizer import clean_text
from app.ingestion.parsers import DocumentParser
from app.models.schemas import ChunkRecord
from app.rag.chunking import TextChunker


class IngestionPipeline:
    """Convert raw documents into chunk records ready for embedding/indexing."""

    def __init__(self, parser: DocumentParser, chunker: TextChunker) -> None:
        self._parser = parser
        self._chunker = chunker

    def process_document(
        self,
        file_path: Path,
        document_name: str,
        version: str,
    ) -> list[ChunkRecord]:
        """Parse a document and return chunk records with metadata."""
        elements = self._parser.parse(file_path)
        timestamp = datetime.now(tz=UTC_TIMEZONE).isoformat()
        records: list[ChunkRecord] = []

        for element in elements:
            chunks = self._chunker.split(element.text)
            for chunk in chunks:
                text = clean_text(chunk.text)
                if not text:
                    continue
                if element.element_type == "text" and len(text.split()) < 4:
                    continue
                metadata = {
                    "chunk_id": str(uuid4()),
                    "document_name": document_name,
                    "page_number": element.page_number,
                    "section": element.section,
                    "version": version,
                    "timestamp": timestamp,
                    "chunk_order": chunk.order,
                    "chunk_type": element.element_type,
                    "is_active": True,
                }
                records.append(ChunkRecord(text=text, metadata=metadata))

        return records
