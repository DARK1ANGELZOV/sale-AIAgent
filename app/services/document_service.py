"""Service for document storage, ingestion, and indexing workflows."""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import structlog

from app.core.constants import UTC_TIMEZONE
from app.core.exceptions import IngestionError
from app.ingestion.pipeline import IngestionPipeline
from app.models.schemas import UploadResponse
from app.rag.embeddings import EmbeddingService
from app.services.qdrant_service import QdrantService


class DocumentService:
    """Handle upload persistence and index lifecycle operations."""

    def __init__(
        self,
        storage_path: Path,
        ingestion_pipeline: IngestionPipeline,
        embedding_service: EmbeddingService,
        qdrant_service: QdrantService,
    ) -> None:
        self._storage_path = storage_path
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._ingestion_pipeline = ingestion_pipeline
        self._embedding_service = embedding_service
        self._qdrant_service = qdrant_service
        self._logger = structlog.get_logger(__name__)

    async def ingest_file(
        self,
        source_file: Path,
        original_name: str,
        version: str,
    ) -> UploadResponse:
        """Parse, embed, and index file in Qdrant."""
        chunks = self._ingestion_pipeline.process_document(
            file_path=source_file,
            document_name=original_name,
            version=version,
        )
        if not chunks:
            raise IngestionError("Parsed document contains no chunks")

        embeddings = await asyncio.to_thread(
            self._embedding_service.embed_texts,
            [chunk.text for chunk in chunks],
        )
        vector_size = len(embeddings[0])
        await self._qdrant_service.ensure_collection(vector_size=vector_size)
        await self._qdrant_service.upsert_chunks(chunks=chunks, embeddings=embeddings)

        now = datetime.now(tz=UTC_TIMEZONE)
        self._logger.info(
            "document_indexed",
            document_name=original_name,
            version=version,
            chunks=len(chunks),
            timestamp=now.isoformat(),
        )
        return UploadResponse(
            document_name=original_name,
            version=version,
            chunks_indexed=len(chunks),
            timestamp=now,
        )

    def persist_temp_file(self, temp_path: Path, filename: str) -> Path:
        """Persist uploaded file under unique name in storage."""
        safe_name = filename.replace("/", "_").replace("\\", "_").strip()
        destination = self._storage_path / f"{uuid4()}_{safe_name}"
        shutil.move(str(temp_path), destination)
        return destination

    async def soft_delete(self, document_name: str, version: str | None = None) -> int:
        """Soft-delete vectors for specific document/version."""
        return await self._qdrant_service.soft_delete(
            document_name=document_name,
            version=version,
        )
