"""Tests for refusal behavior when context is missing."""

import asyncio

from app.core.constants import REFUSAL_TEXT
from app.models.schemas import LLMResult, QueryType
from app.rag.citation import CitationValidator
from app.rag.generator import RAGService
from app.rag.retriever import RetrievalResult


class EmptyRetriever:
    """Returns no retrieval results."""

    async def retrieve(
        self,
        question: str,
        version: str | None = None,
        document_names: list[str] | None = None,
    ) -> RetrievalResult:
        return RetrievalResult(hits=[], confidence=0.0)


class DummyLLM:
    """Must not be called in refusal path."""

    async def answer(
        self,
        question: str,
        query_type: QueryType,
        context: str,
    ) -> LLMResult:
        raise AssertionError("LLM should not be called when retrieval is empty")


class DummyMarketIntel:
    """Market enrichment stub."""

    async def build_market_block(self, question: str, hits: list) -> str | None:
        return None


def test_refusal_when_no_retrieved_context() -> None:
    service = RAGService(
        retriever=EmptyRetriever(),  # type: ignore[arg-type]
        llm_service=DummyLLM(),  # type: ignore[arg-type]
        citation_validator=CitationValidator(max_sources=3),
        market_intel_service=DummyMarketIntel(),  # type: ignore[arg-type]
    )

    response = asyncio.run(service.ask("question", QueryType.sales))
    assert response.answer == REFUSAL_TEXT
    assert response.sources == []
    assert response.confidence == 0.0
