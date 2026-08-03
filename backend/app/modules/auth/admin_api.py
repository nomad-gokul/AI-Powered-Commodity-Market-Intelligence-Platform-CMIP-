"""Admin-only routes for role and user management. Every route is gated by
a specific permission via require_permission, not a blanket "is_admin" flag -
this keeps authorization granular and auditable per action.
"""

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import ApiResponse, PageMeta, PaginatedResponse
from app.core.database import get_db_session
from app.modules.auth.dependencies import require_permission
from app.modules.auth.repository import RoleRepository, UserRepository
from app.modules.auth.schemas import AssignRoleRequest, RoleCreate, RoleRead, UserRead
from app.modules.auth.service import RoleService

router = APIRouter(prefix="/roles", tags=["Roles (Admin)"])
users_admin_router = APIRouter(prefix="/users", tags=["Users (Admin)"])


def get_role_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> RoleService:
    return RoleService(RoleRepository(session), UserRepository(session))


@router.post(
    "",
    response_model=ApiResponse[RoleRead],
    status_code=201,
    dependencies=[Depends(require_permission("roles:write"))],
)
async def create_role(
    payload: RoleCreate,
    service: Annotated[RoleService, Depends(get_role_service)],
) -> ApiResponse[RoleRead]:
    role = await service.create_role(payload.name, payload.description, payload.permissions)
    return ApiResponse(data=RoleRead.model_validate(role))


@router.get(
    "",
    response_model=ApiResponse[list[RoleRead]],
    dependencies=[Depends(require_permission("roles:read"))],
)
async def list_roles(
    service: Annotated[RoleService, Depends(get_role_service)],
) -> ApiResponse[list[RoleRead]]:
    roles = await service.list_roles()
    return ApiResponse(data=[RoleRead.model_validate(r) for r in roles])


@users_admin_router.get(
    "",
    response_model=PaginatedResponse[UserRead],
    dependencies=[Depends(require_permission("users:read"))],
)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[UserRead]:
    repo = UserRepository(session)
    users = await repo.list(offset=(page - 1) * page_size, limit=page_size)
    total = await repo.count()
    return PaginatedResponse(
        data=[UserRead.model_validate(u) for u in users],
        meta=PageMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


@users_admin_router.post(
    "/{user_id}/roles",
    response_model=ApiResponse[UserRead],
    dependencies=[Depends(require_permission("users:write"))],
)
async def assign_role_to_user(
    user_id: uuid.UUID,
    payload: AssignRoleRequest,
    service: Annotated[RoleService, Depends(get_role_service)],
) -> ApiResponse[UserRead]:
    user = await service.assign_role(user_id, payload.role_id)
    return ApiResponse(data=UserRead.model_validate(user))
