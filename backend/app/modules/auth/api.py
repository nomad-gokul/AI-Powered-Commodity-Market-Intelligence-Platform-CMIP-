"""HTTP routes for self-service auth: register, login, refresh, logout, profile."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import ApiResponse
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.rate_limit import rate_limit
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.repository import RefreshTokenRepository, RoleRepository, UserRepository
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    UserRead,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])
users_router = APIRouter(prefix="/users", tags=["Users"])


def get_auth_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> AuthService:
    settings = get_settings()
    return AuthService(
        user_repo=UserRepository(session),
        role_repo=RoleRepository(session),
        refresh_token_repo=RefreshTokenRepository(session),
        audit_service=AuditService(AuditLogRepository(session)),
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )


@router.post("/register", response_model=ApiResponse[UserRead], status_code=201)
async def register(
    payload: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> ApiResponse[UserRead]:
    user = await service.register(payload.email, payload.full_name, payload.password)
    return ApiResponse(data=UserRead.model_validate(user))


@router.post(
    "/login",
    response_model=ApiResponse[TokenPairResponse],
    dependencies=[
        Depends(
            rate_limit(
                "login",
                get_settings().login_rate_limit_attempts,
                get_settings().login_rate_limit_window_seconds,
            )
        )
    ],
)
async def login(
    payload: LoginRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> ApiResponse[TokenPairResponse]:
    client_host = request.client.host if request.client else None
    _, tokens = await service.login(payload.email, payload.password, ip_address=client_host)
    return ApiResponse(data=tokens)


@router.post("/refresh", response_model=ApiResponse[TokenPairResponse])
async def refresh(
    payload: RefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> ApiResponse[TokenPairResponse]:
    tokens = await service.refresh(payload.refresh_token)
    return ApiResponse(data=tokens)


@router.post("/logout", status_code=204)
async def logout(
    payload: RefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await service.logout(payload.refresh_token)


@users_router.get("/me", response_model=ApiResponse[UserRead])
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> ApiResponse[UserRead]:
    return ApiResponse(data=UserRead.model_validate(current_user))
