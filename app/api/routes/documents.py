"""Document management API routes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.deps import get_current_user, get_document_service
from app.core.exceptions import IngestionError, UnsupportedFileTypeError
from app.models.schemas import UploadResponse
from app.services.document_service import DocumentService
from app.services.auth_service import AuthUser

router = APIRouter(prefix="/documents", tags=["documents"])
logger = structlog.get_logger(__name__)


class SoftDeleteRequest(BaseModel):
    """Payload for soft-deleting indexed versions."""

    document_name: str
    version: str | None = None


class SoftDeleteResponse(BaseModel):
    """Result of soft-delete request."""

    operation_id: int


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    version: str = Form(...),
    document_service: DocumentService = Depends(get_document_service),
    current_user: AuthUser = Depends(get_current_user),
) -> UploadResponse:
    """Upload file and push its chunks to vector DB."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".xlsx"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Allowed: pdf, docx, xlsx",
        )

    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_file = Path(tmp.name)
            content = await file.read()
            if not content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty",
                )
            tmp.write(content)

        stored_path = document_service.persist_temp_file(
            temp_path=temp_file,
            filename=file.filename or f"unnamed{suffix}",
        )
        result = await document_service.ingest_file(
            source_file=stored_path,
            original_name=file.filename or stored_path.name,
            version=version,
        )
        logger.info(
            "document_uploaded",
            document_name=result.document_name,
            version=result.version,
            chunks_indexed=result.chunks_indexed,
            user_id=current_user.id,
        )
        return result
    except (UnsupportedFileTypeError, IngestionError) as exc:
        logger.error("upload_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        if temp_file and temp_file.exists():
            os.unlink(temp_file)


@router.post("/soft-delete", response_model=SoftDeleteResponse)
async def soft_delete_document(
    payload: SoftDeleteRequest,
    document_service: DocumentService = Depends(get_document_service),
    current_user: AuthUser = Depends(get_current_user),
) -> SoftDeleteResponse:
    """Soft-delete vectors for old versions."""
    operation_id = await document_service.soft_delete(
        document_name=payload.document_name,
        version=payload.version,
    )
    logger.info(
        "document_soft_deleted",
        document_name=payload.document_name,
        version=payload.version,
        operation_id=operation_id,
        user_id=current_user.id,
    )
    return SoftDeleteResponse(operation_id=operation_id)
