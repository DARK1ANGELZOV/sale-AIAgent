"""FastAPI dependencies."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.rag.generator import RAGService
from app.services.auth_service import AuthService, AuthUser
from app.services.container import ServiceContainer
from app.services.document_service import DocumentService

bearer_scheme = HTTPBearer(auto_error=False)


def get_container(request: Request) -> ServiceContainer:
    """Return application-level service container."""
    return request.app.state.container


def get_rag_service(request: Request) -> RAGService:
    """Provide RAG service dependency."""
    return get_container(request).rag_service


def get_document_service(request: Request) -> DocumentService:
    """Provide document service dependency."""
    return get_container(request).document_service


def get_auth_service(request: Request) -> AuthService:
    """Provide auth service dependency."""
    return get_container(request).auth_service


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthUser:
    """Validate bearer token and return current user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization required",
        )

    user = await auth_service.get_user_by_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return user
