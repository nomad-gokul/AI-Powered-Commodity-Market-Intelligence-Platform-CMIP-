"""FastAPI dependencies for authentication and permission-based authorization.

get_current_token_payload decodes the JWT only (no DB hit) - sufficient for
permission checks since roles/permissions are embedded in the token. Routes
that need the live User row (e.g. profile, is_active re-check) use
get_current_user, which does hit the database.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import AccessTokenPayload, decode_access_token
from app.modules.auth.domain import PermissionSet
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> AccessTokenPayload:
    if credentials is None:
        raise UnauthorizedError("Missing bearer token")
    return decode_access_token(credentials.credentials)


async def get_current_user(
    payload: Annotated[AccessTokenPayload, Depends(get_current_token_payload)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    user = await UserRepository(session).get_by_id(uuid.UUID(payload.sub))
    if user is None or not user.is_active:
        raise UnauthorizedError("Account is no longer active")
    return user


def require_permission(
    permission: str,
) -> Callable[[AccessTokenPayload], Awaitable[AccessTokenPayload]]:
    """Dependency factory: `Depends(require_permission("audit_logs:read"))`.

    Checks the permission embedded in the access token - see
    AccessTokenPayload's docstring for the staleness tradeoff this implies.
    """

    async def dependency(
        payload: Annotated[AccessTokenPayload, Depends(get_current_token_payload)],
    ) -> AccessTokenPayload:
        if not PermissionSet(payload.permissions).has(permission):
            raise ForbiddenError(f"Missing required permission: {permission}")
        return payload

    return dependency
