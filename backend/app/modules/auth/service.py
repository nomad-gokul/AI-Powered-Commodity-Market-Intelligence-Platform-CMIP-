"""Application services for registration, login, token refresh, and logout.

AuditService is injected and called directly rather than through a
repository - this is a deliberate, documented exception to "modules only
read each other's repositories": audit logging has no business rules of
its own to bypass (it's a write-only cross-cutting concern, like logging),
so calling it as a service carries none of the coupling risk the
repository-only rule exists to prevent.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.common.base_service import BaseService
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.audit.service import AuditService
from app.modules.auth.domain import RefreshTokenRecord, RefreshTokenStatus, evaluate_refresh_token
from app.modules.auth.models import RefreshToken, Role, User
from app.modules.auth.repository import RefreshTokenRepository, RoleRepository, UserRepository
from app.modules.auth.schemas import TokenPairResponse

DEFAULT_SELF_REGISTRATION_ROLE = "viewer"


class AuthService(BaseService):
    def __init__(
        self,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        refresh_token_repo: RefreshTokenRepository,
        audit_service: AuditService,
        *,
        refresh_token_expire_days: int,
    ) -> None:
        super().__init__()
        self.user_repo = user_repo
        self.role_repo = role_repo
        self.refresh_token_repo = refresh_token_repo
        self.audit_service = audit_service
        self.refresh_token_expire_days = refresh_token_expire_days

    async def register(self, email: str, full_name: str, password: str) -> User:
        if await self.user_repo.get_by_email(email) is not None:
            raise ConflictError(f"An account with email {email} already exists")

        default_role = await self.role_repo.get_by_name(DEFAULT_SELF_REGISTRATION_ROLE)
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
            roles=[default_role] if default_role else [],
        )
        created = await self.user_repo.create(user)
        await self.audit_service.record(
            user_id=created.id, action="user.register", resource_type="user", resource_id=created.id
        )
        self.logger.info("user_registered", user_id=str(created.id))
        return created

    async def login(
        self, email: str, password: str, *, ip_address: str | None = None
    ) -> tuple[User, TokenPairResponse]:
        user = await self.user_repo.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")
        if not user.is_active:
            raise UnauthorizedError("This account has been deactivated")

        tokens = await self._issue_token_pair(user)
        await self.audit_service.record(
            user_id=user.id,
            action="user.login",
            resource_type="user",
            resource_id=user.id,
            ip_address=ip_address,
        )
        self.logger.info("user_logged_in", user_id=str(user.id))
        return user, tokens

    async def refresh(self, raw_refresh_token: str) -> TokenPairResponse:
        token_hash = hash_refresh_token(raw_refresh_token)
        existing = await self.refresh_token_repo.get_by_token_hash(token_hash)
        if existing is None:
            raise UnauthorizedError("Invalid refresh token")

        status = evaluate_refresh_token(
            RefreshTokenRecord(
                id=existing.id,
                user_id=existing.user_id,
                expires_at=existing.expires_at,
                revoked_at=existing.revoked_at,
            )
        )

        if status is RefreshTokenStatus.REVOKED:
            # A revoked token being presented again means it was stolen and
            # already used by someone else (or us) after rotation - the only
            # safe response is to kill every active session for this user.
            await self.refresh_token_repo.revoke_all_for_user(existing.user_id)
            await self.audit_service.record(
                user_id=existing.user_id,
                action="auth.refresh_token_reuse_detected",
                resource_type="refresh_token",
                resource_id=existing.id,
            )
            self.logger.warning("refresh_token_reuse_detected", user_id=str(existing.user_id))
            raise UnauthorizedError("Session invalidated. Please log in again.")

        if status is RefreshTokenStatus.EXPIRED:
            raise UnauthorizedError("Refresh token has expired. Please log in again.")

        user = await self.user_repo.get_by_id(existing.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Account is no longer active")

        existing.revoked_at = datetime.now(UTC)
        tokens = await self._issue_token_pair(user)
        new_token_hash = hash_refresh_token(tokens.refresh_token)
        new_record = await self.refresh_token_repo.get_by_token_hash(new_token_hash)
        if new_record is not None:
            existing.replaced_by_token_id = new_record.id

        return tokens

    async def logout(self, raw_refresh_token: str) -> None:
        token_hash = hash_refresh_token(raw_refresh_token)
        existing = await self.refresh_token_repo.get_by_token_hash(token_hash)
        if existing is not None and existing.revoked_at is None:
            existing.revoked_at = datetime.now(UTC)
            await self.refresh_token_repo.session.flush()

    async def _issue_token_pair(self, user: User) -> TokenPairResponse:
        roles = [role.name for role in user.roles]
        permissions = sorted({perm for role in user.roles for perm in role.permissions})
        access_token = create_access_token(str(user.id), roles, permissions)

        raw_refresh_token = generate_refresh_token()
        refresh_token = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=self.refresh_token_expire_days),
        )
        await self.refresh_token_repo.create(refresh_token)

        return TokenPairResponse(access_token=access_token, refresh_token=raw_refresh_token)


class RoleService(BaseService):
    def __init__(self, role_repo: RoleRepository, user_repo: UserRepository) -> None:
        super().__init__()
        self.role_repo = role_repo
        self.user_repo = user_repo

    async def create_role(self, name: str, description: str | None, permissions: list[str]) -> Role:
        if await self.role_repo.get_by_name(name) is not None:
            raise ConflictError(f"Role '{name}' already exists")
        role = Role(name=name, description=description, permissions=permissions)
        return await self.role_repo.create(role)

    async def list_roles(self) -> list[Role]:
        return await self.role_repo.list(limit=100)

    async def assign_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        role = await self.role_repo.get_by_id(role_id)
        if role is None:
            raise NotFoundError(f"Role {role_id} not found")
        if role not in user.roles:
            user.roles.append(role)
            await self.role_repo.session.flush()
        return user
