"""Main RAG orchestration service."""

from __future__ import annotations

import re
import time
from datetime import datetime

from app.core.constants import REFUSAL_TEXT, UTC_TIMEZONE
from app.core.exceptions import AppError, CitationValidationError
from app.models.schemas import AnswerMode, AskResponse, QueryType, SearchHit, TokenUsage
from app.rag.citation import CitationValidator
from app.rag.retriever import Retriever
from app.services.llm_service import LLMService
from app.services.market_intel_service import MarketIntelService

EXTRACTIVE_CONFIDENCE_FLOOR = 0.15


class RAGService:
    """Run retrieval + generation + citation enforcement."""

    def __init__(
        self,
        retriever: Retriever,
        llm_service: LLMService,
        citation_validator: CitationValidator,
        market_intel_service: MarketIntelService,
    ) -> None:
        self._retriever = retriever
        self._llm_service = llm_service
        self._citation_validator = citation_validator
        self._market_intel_service = market_intel_service
        self._logger = _get_logger(__name__)

    async def ask(
        self,
        question: str,
        query_type: QueryType,
        version: str | None = None,
        mode: AnswerMode = AnswerMode.standard,
        document_names: list[str] | None = None,
    ) -> AskResponse:
        """Return strict-RAG answer and validated citations."""
        started = time.perf_counter()
        retrieval = await self._retriever.retrieve(
            question=question,
            version=version,
            document_names=document_names,
        )

        if not retrieval.hits:
            return self._build_refusal_response(started)

        context = self._build_context(retrieval.hits)
        question_profile = self._build_question_profile(question=question, query_type=query_type)

        try:
            llm_result = await self._llm_service.answer(
                question=question,
                query_type=query_type,
                context=context,
                question_profile=question_profile,
                response_mode=mode,
            )
        except AppError:
            if retrieval.confidence >= EXTRACTIVE_CONFIDENCE_FLOOR:
                llm_result = _extractive_result(
                    self._build_extractive_fallback_answer(hits=retrieval.hits, mode=mode)
                )
            else:
                return self._build_refusal_response(started)

        if llm_result.answer.strip() == REFUSAL_TEXT:
            if retrieval.confidence >= EXTRACTIVE_CONFIDENCE_FLOOR:
                llm_result = _extractive_result(
                    self._build_extractive_fallback_answer(hits=retrieval.hits, mode=mode)
                )
            else:
                return self._build_refusal_response(started)

        answer = self._apply_mode(answer=llm_result.answer, mode=mode, hits=retrieval.hits)

        sources = self._citation_validator.build_sources(retrieval.hits)
        if not sources or not self._citation_validator.validate(sources, retrieval.hits):
            raise CitationValidationError("Citation validation failed")

        market_block = await self._market_intel_service.build_market_block(
            question=question,
            hits=retrieval.hits,
        )
        market_enriched = bool(market_block)
        if market_block:
            answer = f"{answer}\n\n{market_block}"
        if not self._has_mermaid_block(answer):
            answer = f"{answer}\n\n{self._build_retrieval_mermaid_block(retrieval.hits)}"

        final_answer = self._citation_validator.format_answer(answer, sources)
        used_documents = sorted({source.document_name for source in sources})
        processing_ms = int((time.perf_counter() - started) * 1000)

        response = AskResponse(
            answer=final_answer,
            sources=sources,
            confidence=round(retrieval.confidence, 4),
            used_documents=used_documents,
            timestamp=datetime.now(tz=UTC_TIMEZONE),
            processing_time_ms=processing_ms,
            token_usage=TokenUsage(
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
            ),
        )
        self._logger.info(
            "ask_completed",
            confidence=response.confidence,
            processing_time_ms=response.processing_time_ms,
            used_documents=response.used_documents,
            mode=mode.value,
            market_enriched=market_enriched,
        )
        return response

    def _build_context(self, hits: list[SearchHit]) -> str:
        blocks: list[str] = []
        for index, hit in enumerate(hits, start=1):
            metadata = hit.metadata
            blocks.append(
                (
                    f"[Source {index}] "
                    f"Document={metadata.get('document_name', 'unknown')} "
                    f"Page={metadata.get('page_number', 'n/a')} "
                    f"Section={metadata.get('section', 'n/a')} "
                    f"Version={metadata.get('version', 'unknown')}\n"
                    f"{hit.text}"
                )
            )
        return "\n\n".join(blocks)

    def _build_question_profile(self, question: str, query_type: QueryType) -> str:
        request_kind = self._detect_request_kind(question)
        complexity = self._detect_complexity(question)
        return (
            f"- Query kind: {request_kind}\n"
            f"- Complexity: {complexity}\n"
            f"- Domain: {query_type.value}"
        )

    def _detect_request_kind(self, question: str) -> str:
        q = question.lower()
        if any(token in q for token in ["как", "how", "step", "шаг"]):
            return "practical"
        if any(token in q for token in ["сравни", "compare", "difference", "отлич"]):
            return "comparison"
        if any(token in q for token in ["почему", "why", "reason", "причин"]):
            return "analytical"
        return "informational"

    def _detect_complexity(self, question: str) -> str:
        words = len(question.split())
        if words <= 6:
            return "basic"
        if words <= 16:
            return "advanced"
        return "expert"

    def _build_extractive_fallback_answer(self, hits: list[SearchHit], mode: AnswerMode) -> str:
        lines: list[str] = []
        hits_limit = 1 if mode == AnswerMode.brief else (5 if mode == AnswerMode.deep else 3)

        for hit in hits[:hits_limit]:
            section = str(hit.metadata.get("section", "n/a"))
            snippet = " ".join(hit.text.split())[:280].strip()
            if snippet:
                lines.append(f"- [{section}] {snippet}")

        if not lines:
            return REFUSAL_TEXT

        if mode == AnswerMode.brief:
            return "Найдено в базе знаний: " + lines[0][2:]
        return "Найдено в документации:\n" + "\n".join(lines)

    def _apply_mode(self, answer: str, mode: AnswerMode, hits: list[SearchHit]) -> str:
        text = answer.strip()
        if text == REFUSAL_TEXT:
            return text

        if mode == AnswerMode.brief:
            brief = _first_sentences(text, max_sentences=3)
            return brief or text

        if mode == AnswerMode.deep and len(text.split()) < 80:
            detail_lines = []
            for hit in hits[:3]:
                section = str(hit.metadata.get("section", "n/a"))
                snippet = " ".join(hit.text.split())[:220].strip()
                if snippet:
                    detail_lines.append(f"- {section}: {snippet}")
            if detail_lines:
                return f"{text}\n\nДополнительно из контекста:\n" + "\n".join(detail_lines)
        return text

    def _build_refusal_response(self, started: float) -> AskResponse:
        processing_ms = int((time.perf_counter() - started) * 1000)
        return AskResponse(
            answer=REFUSAL_TEXT,
            sources=[],
            confidence=0.0,
            used_documents=[],
            timestamp=datetime.now(tz=UTC_TIMEZONE),
            processing_time_ms=processing_ms,
            token_usage=TokenUsage(),
        )

    def _has_mermaid_block(self, answer: str) -> bool:
        return "```mermaid" in answer

    def _build_retrieval_mermaid_block(self, hits: list[SearchHit]) -> str:
        top_hits = hits[:4]
        labels = ", ".join(f'"S{idx}"' for idx, _ in enumerate(top_hits, start=1))
        values = ", ".join(f"{hit.score:.3f}" for hit in top_hits)

        return (
            "```mermaid\n"
            "xychart-beta\n"
            '    title "Retrieval relevance scores"\n'
            f"    x-axis [{labels}]\n"
            '    y-axis "score" 0 --> 1\n'
            f"    bar [{values}]\n"
            "```"
        )


def _first_sentences(text: str, max_sentences: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    cleaned = [sentence.strip() for sentence in sentences if sentence.strip()]
    return " ".join(cleaned[:max_sentences]).strip()


def _extractive_result(answer: str):  # noqa: ANN201
    from app.models.schemas import LLMResult

    return LLMResult(answer=answer, input_tokens=0, output_tokens=0)


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
