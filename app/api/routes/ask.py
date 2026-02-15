"""Question-answer API route."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_rag_service
from app.models.schemas import AskRequest, AskResponse
from app.rag.generator import RAGService
from app.services.auth_service import AuthUser

router = APIRouter(tags=["ask"])
logger = structlog.get_logger(__name__)


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    payload: AskRequest,
    rag_service: RAGService = Depends(get_rag_service),
    current_user: AuthUser = Depends(get_current_user),
) -> AskResponse:
    """Answer user question with strict RAG constraints."""
    response = await rag_service.ask(
        question=payload.question,
        query_type=payload.type,
        version=payload.version,
        mode=payload.mode,
    )
    logger.info(
        "ask_request",
        question=payload.question,
        query_type=payload.type.value,
        mode=payload.mode.value,
        used_documents=response.used_documents,
        confidence=response.confidence,
        processing_time_ms=response.processing_time_ms,
        input_tokens=response.token_usage.input_tokens,
        output_tokens=response.token_usage.output_tokens,
        user_id=current_user.id,
    )
    return response
