"""Embedding service with lazy model loading, cache, and retries."""

from __future__ import annotations

import hashlib
import threading
from typing import Sequence

from cachetools import LRUCache
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.exceptions import EmbeddingError, ModelMemoryError


class EmbeddingService:
    """Generate sentence embeddings in CPU-friendly batches."""

    def __init__(
        self,
        model_name: str,
        batch_size: int,
        cache_size: int,
        retry_attempts: int,
    ) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._cache = LRUCache(maxsize=cache_size)
        self._retry_attempts = retry_attempts
        self._model = None
        self._lock = threading.Lock()

    def _lazy_load_model(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self._model_name)
            except MemoryError as exc:
                raise ModelMemoryError(
                    "Not enough memory to load embedding model"
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise EmbeddingError(
                    f"Failed to load embedding model: {self._model_name}"
                ) from exc

    def _hash_text(self, text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed non-empty texts preserving original order."""
        retrier = Retrying(
            wait=wait_exponential(multiplier=1, min=1, max=8),
            stop=stop_after_attempt(self._retry_attempts),
            retry=retry_if_exception_type(EmbeddingError),
            reraise=True,
        )

        for attempt in retrier:
            with attempt:
                return self._embed_once(texts)
        raise EmbeddingError("Embedding retries exhausted")

    def _embed_once(self, texts: Sequence[str]) -> list[list[float]]:
        self._lazy_load_model()
        cleaned = [text.strip() for text in texts]
        if not any(cleaned):
            raise EmbeddingError("No non-empty chunks for embedding")

        result_vectors: list[list[float] | None] = [None] * len(cleaned)
        misses: list[str] = []
        miss_positions: list[int] = []
        miss_keys: list[str] = []

        for idx, text in enumerate(cleaned):
            if not text:
                continue
            key = self._hash_text(text)
            cached = self._cache.get(key)
            if cached is not None:
                result_vectors[idx] = cached
            else:
                misses.append(text)
                miss_positions.append(idx)
                miss_keys.append(key)

        if misses:
            try:
                vectors = list(self._model.embed(misses, batch_size=self._batch_size))  # type: ignore[union-attr]
            except MemoryError as exc:
                raise ModelMemoryError("Memory overflow during embedding") from exc
            except Exception as exc:  # noqa: BLE001
                raise EmbeddingError("Embedding generation failed") from exc

            for position, key, vector in zip(miss_positions, miss_keys, vectors):
                vector_list = vector.tolist()
                self._cache[key] = vector_list
                result_vectors[position] = vector_list

        embedded = [vector for vector in result_vectors if vector is not None]
        if not embedded:
            raise EmbeddingError("Embedding output is empty")
        return embedded
