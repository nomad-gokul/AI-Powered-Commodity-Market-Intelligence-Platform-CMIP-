"""Unit tests for password hashing and JWT primitives."""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_hash_password_is_not_plaintext_and_verifies() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_access_token_round_trip_carries_roles_and_permissions() -> None:
    token = create_access_token("user-123", ["admin"], ["users:read", "users:write"])
    payload = decode_access_token(token)

    assert payload.sub == "user-123"
    assert payload.roles == ["admin"]
    assert payload.permissions == ["users:read", "users:write"]


def test_decode_access_token_rejects_garbage() -> None:
    with pytest.raises(UnauthorizedError):
        decode_access_token("not-a-real-token")


def test_decode_access_token_rejects_expired_token() -> None:
    settings = get_settings()
    expired_payload = {
        "sub": "user-123",
        "roles": [],
        "permissions": [],
        "exp": datetime.now(UTC) - timedelta(minutes=1),
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )

    with pytest.raises(UnauthorizedError):
        decode_access_token(expired_token)


def test_generate_refresh_token_is_high_entropy_and_unique() -> None:
    first = generate_refresh_token()
    second = generate_refresh_token()
    assert first != second
    assert len(first) >= 48


def test_hash_refresh_token_is_deterministic_and_one_way() -> None:
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert hash_refresh_token(token) != token
