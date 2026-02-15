"""Tests for response mode behavior."""

import asyncio

from app.models.schemas import AnswerMode, LLMResult, QueryType, SearchHit
from app.rag.citation import CitationValidator
from app.rag.generator import RAGService
from app.rag.retriever import RetrievalResult


class FixedRetriever:
    """Returns fixed retrieval context."""

    async def retrieve(self, question: str, version: str | None = None) -> RetrievalResult:
        return RetrievalResult(
            hits=[
                SearchHit(
                    id="1",
                    score=0.87,
                    text="AstroSecure 5000 supports role-based access control and audit logs.",
                    metadata={
                        "document_name": "spec.docx",
                        "version": "v1",
                        "page_number": 2,
                        "section": "Security",
                    },
                )
            ],
            confidence=0.87,
        )


class FixedLLM:
    """Returns fixed answer text."""

    async def answer(
        self,
        question: str,
        query_type: QueryType,
        context: str,
        question_profile: str = "",
        response_mode: AnswerMode = AnswerMode.standard,
    ) -> LLMResult:
        return LLMResult(
            answer=(
                "Система поддерживает RBAC и аудит действий пользователей. "
                "Это снижает риски несанкционированного доступа."
            )
        )


class DummyMarketIntel:
    """Market enrichment stub."""

    async def build_market_block(self, question: str, hits: list) -> str | None:
        return None


def _service() -> RAGService:
    return RAGService(
        retriever=FixedRetriever(),  # type: ignore[arg-type]
        llm_service=FixedLLM(),  # type: ignore[arg-type]
        citation_validator=CitationValidator(max_sources=2),
        market_intel_service=DummyMarketIntel(),  # type: ignore[arg-type]
    )


def test_brief_mode_shortens_answer() -> None:
    response = asyncio.run(
        _service().ask(
            question="Какие ключевые меры безопасности?",
            query_type=QueryType.technical,
            mode=AnswerMode.brief,
        )
    )
    assert "Источники:" in response.answer
    assert response.answer.count(".") <= 7


def test_deep_mode_adds_context_details_for_short_answer() -> None:
    response = asyncio.run(
        _service().ask(
            question="Раскрой подробнее",
            query_type=QueryType.technical,
            mode=AnswerMode.deep,
        )
    )
    assert "Дополнительно из контекста" in response.answer
