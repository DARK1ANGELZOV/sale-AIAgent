"""Retriever service for vector search + reranking + threshold filtering."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import RetrievalError
from app.models.schemas import SearchHit
from app.rag.embeddings import EmbeddingService
from app.rag.reranker import HybridReranker, tokenize_text


class VectorSearchClient(Protocol):
    """Protocol for vector DB search clients."""

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        version: str | None = None,
    ) -> list[SearchHit]:
        """Return scored hits."""


@dataclass(slots=True)
class RetrievalResult:
    """Retrieval output with relevance confidence."""

    hits: list[SearchHit]
    confidence: float


class Retriever:
    """Embed user query, rerank candidates, and return best chunks."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        qdrant_service: VectorSearchClient,
        top_k: int,
        similarity_threshold: float,
        candidate_k: int | None = None,
        reranker: HybridReranker | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._qdrant_service = qdrant_service
        self._top_k = top_k
        self._candidate_k = max(top_k, candidate_k or top_k)
        self._similarity_threshold = similarity_threshold
        self._reranker = reranker or HybridReranker()
        self._logger = _get_logger(__name__)

    async def retrieve(
        self,
        question: str,
        version: str | None = None,
    ) -> RetrievalResult:
        """Return hits that pass configured relevance threshold."""
        try:
            vectors = await asyncio.to_thread(self._embedding_service.embed_texts, [question])
            query_vector = vectors[0]
            hits = await self._qdrant_service.search(
                query_vector=query_vector,
                top_k=self._candidate_k,
                version=version,
            )
            if not hits and version:
                # Fallback when user selected an outdated/incorrect version.
                hits = await self._qdrant_service.search(
                    query_vector=query_vector,
                    top_k=self._candidate_k,
                    version=None,
                )
        except Exception as exc:  # noqa: BLE001
            raise RetrievalError("Retrieval pipeline failed") from exc

        reranked = self._reranker.rerank(question=question, hits=hits, top_k=self._top_k)
        filtered = [hit for hit in reranked if hit.score >= self._similarity_threshold]

        if not filtered and reranked:
            query_tokens = _tokenize(question)
            lexical_ranked = sorted(
                reranked,
                key=lambda hit: (_lexical_overlap(query_tokens, hit.text), hit.score),
                reverse=True,
            )
            best_lexical = lexical_ranked[0]
            best_lexical_overlap = _lexical_overlap(query_tokens, best_lexical.text)

            if best_lexical_overlap >= 0.2 or (
                best_lexical_overlap > 0.0 and best_lexical.score >= 0.06
            ):
                filtered = [best_lexical]
            else:
                # Soft fallback for short/ambiguous queries.
                best = max(reranked, key=lambda hit: hit.score)
                short_query_cutoff = max(0.05, self._similarity_threshold * 0.25)
                if len(question.split()) <= 3 and best.score >= short_query_cutoff:
                    filtered = [best]
                elif best.score >= 0.02:
                    # Last-resort fallback: keep best candidate to avoid false refusals.
                    filtered = [best]

        filtered = _deduplicate_hits(filtered, limit=self._top_k)
        confidence = max((hit.score for hit in filtered), default=0.0)
        self._logger.info(
            "retrieval_stats",
            raw_hits=len(hits),
            reranked_hits=len(reranked),
            filtered_hits=len(filtered),
            confidence=round(confidence, 4),
            threshold=self._similarity_threshold,
        )
        return RetrievalResult(hits=filtered, confidence=confidence)


def _tokenize(text: str) -> set[str]:
    return tokenize_text(text)


def _lexical_overlap(question_tokens: set[str], chunk_text: str) -> float:
    if not question_tokens:
        return 0.0
    chunk_tokens = _tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0
    shared = question_tokens.intersection(chunk_tokens)
    return len(shared) / len(question_tokens)


def _deduplicate_hits(hits: list[SearchHit], limit: int) -> list[SearchHit]:
    deduped: list[SearchHit] = []
    seen: set[tuple[str, str, str]] = set()
    for hit in hits:
        key = (
            str(hit.metadata.get("document_name", "")),
            str(hit.metadata.get("section", "")),
            " ".join(hit.text.split())[:220],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped


def _get_logger(name: str):  # noqa: ANN201
    try:
        import structlog

        return structlog.get_logger(name)
    except Exception:  # noqa: BLE001
        import logging

        std_logger = logging.getLogger(name)

        class _Adapter:
            def info(self, event: str, **kwargs: object) -> None:
                if kwargs:
                    std_logger.info("%s | %s", event, kwargs)
                else:
                    std_logger.info(event)

        return _Adapter()
