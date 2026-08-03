"""Password hashing and JWT primitives.

Two distinct hashing strategies are used deliberately:

- Passwords are low-entropy and user-chosen, so they use bcrypt (slow by
  design, resists offline brute force).
- Refresh tokens are high-entropy random strings (secrets.token_urlsafe),
  so a fast SHA-256 hash is sufficient - bcrypt's deliberate slowness would
  only add latency with no security benefit against an unguessable token.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AccessTokenPayload(BaseModel):
    """Decoded access token claims.

    Roles and permissions are embedded in the token itself so permission
    checks don't require a DB round trip on every request. The tradeoff:
    a permission change (e.g. revoking a role) takes up to
    access_token_expire_minutes to fully propagate, since existing access
    tokens remain valid until they expire. Refresh tokens are checked
    against the DB on every use, so revoking a session takes effect
    immediately at the next refresh.
    """

    sub: str
    roles: list[str]
    permissions: list[str]
    exp: datetime


def hash_password(plain_password: str) -> str:
    return str(_pwd_context.hash(plain_password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bool(_pwd_context.verify(plain_password, hashed_password))


def create_access_token(user_id: str, roles: list[str], permissions: list[str]) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "roles": roles, "permissions": permissions, "exp": expire}
    return str(jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm))


def decode_access_token(token: str) -> AccessTokenPayload:
    settings = get_settings()
    try:
        raw = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired access token") from exc
    return AccessTokenPayload.model_validate(raw)


def generate_refresh_token() -> str:
    """A high-entropy opaque token - not a JWT, so it carries no claims and
    must be looked up in the database to be validated or revoked."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
