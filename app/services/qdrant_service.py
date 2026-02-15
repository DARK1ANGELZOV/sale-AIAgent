"""Async wrapper over Qdrant operations."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from qdrant_client import AsyncQdrantClient, models

from app.core.exceptions import QdrantUnavailableError
from app.models.schemas import ChunkRecord, SearchHit


class QdrantService:
    """Manage collection lifecycle, indexing, and search operations."""

    def __init__(
        self,
        mode: str,
        url: str,
        path: Path,
        collection_name: str,
        timeout_sec: int,
        api_key: str | None = None,
    ) -> None:
        self._collection_name = collection_name
        self._mode = mode
        if mode == "local":
            path.mkdir(parents=True, exist_ok=True)
            self._client = AsyncQdrantClient(path=str(path), timeout=timeout_sec)
        else:
            self._client = AsyncQdrantClient(
                url=url,
                api_key=api_key,
                timeout=timeout_sec,
            )

    async def healthcheck(self) -> None:
        """Raise error when Qdrant is unavailable."""
        try:
            await self._client.get_collections()
        except Exception as exc:  # noqa: BLE001
            raise QdrantUnavailableError("Qdrant is unavailable") from exc

    async def ensure_collection(self, vector_size: int) -> None:
        """Create collection if missing."""
        exists = False
        try:
            exists = await self._client.collection_exists(self._collection_name)
            if exists:
                details = await self._client.get_collection(self._collection_name)
                vectors = details.config.params.vectors
                current_size = None
                if hasattr(vectors, "size"):
                    current_size = int(vectors.size)  # type: ignore[arg-type]
                if isinstance(vectors, dict):
                    first_key = next(iter(vectors))
                    current_size = int(vectors[first_key].size)
                if current_size == vector_size:
                    return

                await self._client.delete_collection(self._collection_name)
                exists = False
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if "not found" not in message:
                raise QdrantUnavailableError(
                    "Failed to check Qdrant collection"
                ) from exc

        if not exists:
            try:
                await self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                raise QdrantUnavailableError(
                    "Failed to create Qdrant collection"
                ) from exc

    async def upsert_chunks(
        self, chunks: list[ChunkRecord], embeddings: list[list[float]]
    ) -> None:
        """Upsert chunk vectors and metadata."""
        points: list[models.PointStruct] = []
        for chunk, vector in zip(chunks, embeddings):
            point_id = chunk.metadata.get("chunk_id", str(uuid4()))
            payload = {"text": chunk.text, **chunk.metadata}
            points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

        try:
            await self._client.upsert(
                collection_name=self._collection_name,
                points=points,
                wait=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise QdrantUnavailableError("Failed to upsert data into Qdrant") from exc

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        version: str | None = None,
        document_names: list[str] | None = None,
    ) -> list[SearchHit]:
        """Return top-k active hits with optional version filtering."""
        conditions = []
        if version:
            conditions.append(
                models.FieldCondition(
                    key="version",
                    match=models.MatchValue(value=version),
                )
            )
        if document_names:
            conditions.append(
                models.FieldCondition(
                    key="document_name",
                    match=models.MatchAny(any=document_names),
                )
            )
        query_filter = models.Filter(must=conditions) if conditions else None

        try:
            points = await self._client.search(
                collection_name=self._collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:  # noqa: BLE001
            if "not found" in str(exc).lower():
                return []
            raise QdrantUnavailableError("Failed to query Qdrant") from exc

        hits: list[SearchHit] = []
        for point in points:
            payload = point.payload or {}
            if payload.get("is_active", True) is False:
                continue
            text = str(payload.get("text", ""))
            hits.append(
                SearchHit(
                    id=str(point.id),
                    score=float(point.score),
                    text=text,
                    metadata=payload,
                )
            )
        return hits

    async def soft_delete(
        self,
        document_name: str,
        version: str | None = None,
    ) -> int:
        """Soft-delete old versions by setting is_active=false."""
        must_conditions = [
            models.FieldCondition(
                key="document_name",
                match=models.MatchValue(value=document_name),
            ),
            models.FieldCondition(
                key="is_active",
                match=models.MatchValue(value=True),
            ),
        ]
        if version:
            must_conditions.append(
                models.FieldCondition(
                    key="version",
                    match=models.MatchValue(value=version),
                )
            )

        selector = models.FilterSelector(
            filter=models.Filter(
                must=must_conditions,
            )
        )

        try:
            result = await self._client.set_payload(
                collection_name=self._collection_name,
                payload={"is_active": False},
                points=selector,
            )
            return int(result.operation_id or 0)
        except Exception as exc:  # noqa: BLE001
            raise QdrantUnavailableError("Failed to soft-delete vectors") from exc
