"""FastAPI application entrypoint."""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import logging_middleware
from app.api.routes.ask import router as ask_router
from app.api.routes.auth import router as auth_router
from app.api.routes.documents import router as documents_router
from app.api.routes.share import router as share_router
from app.api.routes.web import BASE_DIR, router as web_router
from app.config.settings import get_settings
from app.core.constants import UTC_TIMEZONE
from app.core.exceptions import (
    AppError,
    CitationValidationError,
    EmbeddingError,
    EmptyLLMResponseError,
    IngestionError,
    LLMTimeoutError,
    ModelMemoryError,
    QdrantUnavailableError,
    RetrievalError,
)
from app.logging.setup import configure_logging
from app.services.container import ServiceContainer

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

app = FastAPI(title=settings.app_name, version="1.0.0")
app.middleware("http")(logging_middleware)
app.include_router(ask_router)
app.include_router(documents_router)
app.include_router(auth_router)
app.include_router(share_router)
app.include_router(web_router)
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "web" / "assets")), name="assets")


@app.on_event("startup")
async def on_startup() -> None:
    """Initialize dependencies and verify external services."""
    app.state.container = ServiceContainer(settings)
    await app.state.container.qdrant_service.healthcheck()
    logger.info("startup_completed", environment=settings.environment)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    """Liveness endpoint."""
    return {"status": "ok"}


@app.exception_handler(LLMTimeoutError)
async def llm_timeout_handler(_: Request, exc: LLMTimeoutError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": str(exc)})


@app.exception_handler(QdrantUnavailableError)
async def qdrant_handler(_: Request, exc: QdrantUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(
    IngestionError
)
@app.exception_handler(EmbeddingError)
@app.exception_handler(RetrievalError)
@app.exception_handler(CitationValidationError)
@app.exception_handler(EmptyLLMResponseError)
@app.exception_handler(ModelMemoryError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "timestamp": datetime.now(tz=UTC_TIMEZONE).isoformat(),
        },
    )
