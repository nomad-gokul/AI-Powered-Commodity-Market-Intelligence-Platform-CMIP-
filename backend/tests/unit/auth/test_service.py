"""Unit tests for AuthService, with repositories and AuditService mocked."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import hash_password, hash_refresh_token
from app.modules.auth.models import RefreshToken, Role, User
from app.modules.auth.service import AuthService


def make_user(*, email: str = "trader@cmip.test", password: str = "correct-horse-battery") -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        full_name="Test Trader",
        is_active=True,
        roles=[],
    )


@pytest.fixture
def service() -> tuple[AuthService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    user_repo = AsyncMock()
    role_repo = AsyncMock()
    refresh_token_repo = AsyncMock()
    audit_service = AsyncMock()
    auth_service = AuthService(
        user_repo, role_repo, refresh_token_repo, audit_service, refresh_token_expire_days=30
    )
    return auth_service, user_repo, role_repo, refresh_token_repo, audit_service


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_creates_user_with_default_role(self, service) -> None:
        auth_service, user_repo, role_repo, _, audit_service = service
        user_repo.get_by_email.return_value = None
        viewer_role = Role(id=uuid.uuid4(), name="viewer", permissions=[])
        role_repo.get_by_name.return_value = viewer_role
        user_repo.create.side_effect = lambda u: u

        created = await auth_service.register("new@cmip.test", "New Trader", "a-strong-password")

        assert created.email == "new@cmip.test"
        assert created.roles == [viewer_role]
        audit_service.record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_rejects_duplicate_email(self, service) -> None:
        auth_service, user_repo, *_ = service
        user_repo.get_by_email.return_value = make_user()

        with pytest.raises(ConflictError):
            await auth_service.register("trader@cmip.test", "Trader", "a-strong-password")


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_succeeds_and_issues_tokens(self, service) -> None:
        auth_service, user_repo, _, refresh_token_repo, audit_service = service
        user = make_user(password="a-strong-password")
        user_repo.get_by_email.return_value = user
        refresh_token_repo.create.side_effect = lambda t: t

        logged_in_user, tokens = await auth_service.login("trader@cmip.test", "a-strong-password")

        assert logged_in_user is user
        assert tokens.access_token
        assert tokens.refresh_token
        audit_service.record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_login_rejects_wrong_password(self, service) -> None:
        auth_service, user_repo, *_ = service
        user_repo.get_by_email.return_value = make_user(password="a-strong-password")

        with pytest.raises(UnauthorizedError):
            await auth_service.login("trader@cmip.test", "wrong-password")

    @pytest.mark.asyncio
    async def test_login_rejects_unknown_email(self, service) -> None:
        auth_service, user_repo, *_ = service
        user_repo.get_by_email.return_value = None

        with pytest.raises(UnauthorizedError):
            await auth_service.login("nobody@cmip.test", "whatever")

    @pytest.mark.asyncio
    async def test_login_rejects_deactivated_account(self, service) -> None:
        auth_service, user_repo, *_ = service
        user = make_user(password="a-strong-password")
        user.is_active = False
        user_repo.get_by_email.return_value = user

        with pytest.raises(UnauthorizedError):
            await auth_service.login("trader@cmip.test", "a-strong-password")


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_rejects_unknown_token(self, service) -> None:
        auth_service, _, _, refresh_token_repo, _ = service
        refresh_token_repo.get_by_token_hash.return_value = None

        with pytest.raises(UnauthorizedError):
            await auth_service.refresh("some-raw-token")

    @pytest.mark.asyncio
    async def test_refresh_rejects_expired_token(self, service) -> None:
        auth_service, _, _, refresh_token_repo, _ = service
        raw_token = "raw-refresh-token"
        expired = RefreshToken(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(UTC) - timedelta(days=1),
            revoked_at=None,
        )
        refresh_token_repo.get_by_token_hash.return_value = expired

        with pytest.raises(UnauthorizedError):
            await auth_service.refresh(raw_token)

    @pytest.mark.asyncio
    async def test_refresh_of_revoked_token_invalidates_all_sessions(self, service) -> None:
        auth_service, _, _, refresh_token_repo, audit_service = service
        raw_token = "raw-refresh-token"
        user_id = uuid.uuid4()
        revoked = RefreshToken(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            revoked_at=datetime.now(UTC),
        )
        refresh_token_repo.get_by_token_hash.return_value = revoked

        with pytest.raises(UnauthorizedError):
            await auth_service.refresh(raw_token)

        refresh_token_repo.revoke_all_for_user.assert_awaited_once_with(user_id)
        audit_service.record.assert_awaited_once()
        recorded_action = audit_service.record.call_args.kwargs["action"]
        assert recorded_action == "auth.refresh_token_reuse_detected"

    @pytest.mark.asyncio
    async def test_refresh_of_valid_token_rotates_it(self, service) -> None:
        auth_service, user_repo, _, refresh_token_repo, _ = service
        raw_token = "raw-refresh-token"
        user = make_user()
        valid = RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            revoked_at=None,
        )
        refresh_token_repo.get_by_token_hash.side_effect = [valid, None]
        user_repo.get_by_id.return_value = user
        refresh_token_repo.create.side_effect = lambda t: t

        tokens = await auth_service.refresh(raw_token)

        assert tokens.refresh_token != raw_token
        assert valid.revoked_at is not None


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_revokes_existing_token(self, service) -> None:
        auth_service, _, _, refresh_token_repo, _ = service
        raw_token = "raw-refresh-token"
        existing = RefreshToken(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            token_hash=hash_refresh_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            revoked_at=None,
        )
        refresh_token_repo.get_by_token_hash.return_value = existing

        await auth_service.logout(raw_token)

        assert existing.revoked_at is not None

    @pytest.mark.asyncio
    async def test_logout_is_idempotent_for_unknown_token(self, service) -> None:
        auth_service, _, _, refresh_token_repo, _ = service
        refresh_token_repo.get_by_token_hash.return_value = None

        await auth_service.logout("unknown-token")  # must not raise
