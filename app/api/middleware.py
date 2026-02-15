"""HTTP middleware for request/response logging."""

from __future__ import annotations

import time
from collections.abc import Callable

import structlog
from fastapi import Request, Response

logger = structlog.get_logger(__name__)


async def logging_middleware(request: Request, call_next: Callable) -> Response:
    """Log request timing in structured JSON format."""
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        processing_time_ms=elapsed_ms,
    )
    response.headers["X-Processing-Time-Ms"] = str(elapsed_ms)
    return response
