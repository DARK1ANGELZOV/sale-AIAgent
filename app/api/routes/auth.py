"""Authentication and profile routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import bearer_scheme, get_auth_service, get_current_user
from app.models.schemas import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserProfile,
)
from app.services.auth_service import AuthService, AuthUser

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_profile(user: AuthUser) -> UserProfile:
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        settings=user.settings,
        created_at=user.created_at,
    )


@router.post("/register", response_model=AuthResponse)
async def register(
    payload: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """Register account and return session token."""
    try:
        token, user = await auth_service.register(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AuthResponse(access_token=token, user=_to_user_profile(user))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """Log in and return session token."""
    try:
        token, user = await auth_service.login(email=payload.email, password=payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return AuthResponse(access_token=token, user=_to_user_profile(user))


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """Invalidate current session token."""
    if credentials is not None and credentials.scheme.lower() == "bearer":
        await auth_service.logout(credentials.credentials)
    return {"status": "ok"}


@router.get("/me", response_model=UserProfile)
async def me(current_user: AuthUser = Depends(get_current_user)) -> UserProfile:
    """Return current user profile."""
    return _to_user_profile(current_user)


@router.patch("/me", response_model=UserProfile)
async def update_me(
    payload: UpdateProfileRequest,
    current_user: AuthUser = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserProfile:
    """Update user profile/settings."""
    try:
        user = await auth_service.update_profile(
            user_id=current_user.id,
            display_name=payload.display_name,
            settings=payload.settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_user_profile(user)
