"""Pure business rules for auth: permission evaluation and refresh token
validity. Deliberately has zero SQLAlchemy/FastAPI imports - these are the
two places in the auth module with real rules, so they get real domain
types instead of the ORM model doubling as the domain object.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class PermissionSet:
    """The union of permissions granted by a user's roles.

    Supports exact matches ("documents:upload"), resource wildcards
    ("documents:*"), and a full wildcard ("*") for super-admin roles.
    """

    def __init__(self, permissions: list[str]) -> None:
        self._permissions = frozenset(permissions)

    def has(self, required: str) -> bool:
        if "*" in self._permissions or required in self._permissions:
            return True
        resource = required.split(":", 1)[0]
        return f"{resource}:*" in self._permissions

    def __repr__(self) -> str:
        return f"PermissionSet({sorted(self._permissions)!r})"


@dataclass(frozen=True)
class RefreshTokenRecord:
    """Framework-free projection of a refresh_tokens row, for domain rules."""

    id: UUID
    user_id: UUID
    expires_at: datetime
    revoked_at: datetime | None


class RefreshTokenStatus(StrEnum):
    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"


def evaluate_refresh_token(
    record: RefreshTokenRecord, *, now: datetime | None = None
) -> RefreshTokenStatus:
    """Classify a refresh token's validity.

    A REVOKED result on a token still within its expiry window is a signal
    the caller should treat as potential theft (someone replayed a token
    that was already rotated out) - the service layer uses this
    distinction to decide whether to revoke the user's entire session
    family, not just deny this one request.
    """
    current_time = now or datetime.now(UTC)
    if record.revoked_at is not None:
        return RefreshTokenStatus.REVOKED
    if record.expires_at <= current_time:
        return RefreshTokenStatus.EXPIRED
    return RefreshTokenStatus.VALID
