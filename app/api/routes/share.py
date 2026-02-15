"""Chat sharing routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_auth_service, get_current_user
from app.models.schemas import CreateShareRequest, CreateShareResponse, SharedChatResponse
from app.services.auth_service import AuthService, AuthUser

router = APIRouter(prefix="/share", tags=["share"])


@router.post("", response_model=CreateShareResponse)
async def create_share(
    payload: CreateShareRequest,
    request: Request,
    current_user: AuthUser = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> CreateShareResponse:
    """Create share token for current chat snapshot."""
    token = await auth_service.create_share(
        user_id=current_user.id,
        title=payload.title,
        messages=[message.model_dump() for message in payload.messages],
    )
    base_url = str(request.base_url).rstrip("/")
    return CreateShareResponse(token=token, share_url=f"{base_url}/?share={token}")


@router.get("/{token}", response_model=SharedChatResponse)
async def get_shared_chat(
    token: str,
    auth_service: AuthService = Depends(get_auth_service),
) -> SharedChatResponse:
    """Read shared chat by token."""
    snapshot = await auth_service.get_shared_chat(token)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    return SharedChatResponse(
        title=snapshot.title,
        messages=snapshot.messages,
        created_at=snapshot.created_at,
        owner_display_name=snapshot.owner_display_name,
    )
