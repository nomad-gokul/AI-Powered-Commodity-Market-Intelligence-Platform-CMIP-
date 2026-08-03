"""Unit tests for auth domain rules: PermissionSet and refresh token
validity classification."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.auth.domain import (
    PermissionSet,
    RefreshTokenRecord,
    RefreshTokenStatus,
    evaluate_refresh_token,
)


class TestPermissionSet:
    def test_exact_match(self) -> None:
        assert PermissionSet(["documents:upload"]).has("documents:upload")

    def test_no_match(self) -> None:
        assert not PermissionSet(["documents:upload"]).has("documents:delete")

    def test_resource_wildcard(self) -> None:
        assert PermissionSet(["documents:*"]).has("documents:upload")
        assert PermissionSet(["documents:*"]).has("documents:delete")
        assert not PermissionSet(["documents:*"]).has("reports:read")

    def test_full_wildcard_grants_everything(self) -> None:
        permissions = PermissionSet(["*"])
        assert permissions.has("anything:at_all")
        assert permissions.has("audit_logs:read")

    def test_empty_permission_set_grants_nothing(self) -> None:
        assert not PermissionSet([]).has("documents:read")


class TestEvaluateRefreshToken:
    def _record(self, *, expires_in: timedelta, revoked: bool = False) -> RefreshTokenRecord:
        now = datetime.now(UTC)
        return RefreshTokenRecord(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            expires_at=now + expires_in,
            revoked_at=now if revoked else None,
        )

    def test_valid_token(self) -> None:
        record = self._record(expires_in=timedelta(days=1))
        assert evaluate_refresh_token(record) is RefreshTokenStatus.VALID

    def test_expired_token(self) -> None:
        record = self._record(expires_in=timedelta(days=-1))
        assert evaluate_refresh_token(record) is RefreshTokenStatus.EXPIRED

    def test_revoked_token_takes_priority_over_expiry(self) -> None:
        # Revoked AND expired - revoked must win, since callers use REVOKED
        # specifically as a theft signal distinct from ordinary expiry.
        record = self._record(expires_in=timedelta(days=-1), revoked=True)
        assert evaluate_refresh_token(record) is RefreshTokenStatus.REVOKED

    def test_revoked_but_not_yet_expired(self) -> None:
        record = self._record(expires_in=timedelta(days=1), revoked=True)
        assert evaluate_refresh_token(record) is RefreshTokenStatus.REVOKED
