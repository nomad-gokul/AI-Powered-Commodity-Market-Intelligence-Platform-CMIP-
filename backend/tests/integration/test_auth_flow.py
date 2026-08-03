"""End-to-end auth flow against the real app, database, and Redis:
register -> login -> access a protected route -> refresh -> reuse
detection -> logout, plus RBAC enforcement and login rate limiting.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.models import Role, User

REGISTER_PAYLOAD = {
    "email": "trader@example.com",
    "full_name": "Test Trader",
    "password": "a-genuinely-strong-password",
}


@pytest.mark.asyncio
async def test_register_assigns_default_viewer_role(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["email"] == REGISTER_PAYLOAD["email"]
    assert [r["name"] for r in body["roles"]] == ["viewer"]


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 409
    assert response.json()["error_code"] == "conflict"


@pytest.mark.asyncio
async def test_login_returns_tokens_that_authorize_protected_routes(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    assert login_response.status_code == 200
    tokens = login_response.json()["data"]

    me_response = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["data"]["email"] == REGISTER_PAYLOAD["email"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_rejects_missing_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_viewer_is_forbidden_from_admin_only_route(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    access_token = login_response.json()["data"]["access_token"]

    response = await client.get(
        "/api/v1/audit-logs", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_role_can_read_audit_logs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    await _promote_to_admin(db_session, REGISTER_PAYLOAD["email"])

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    access_token = login_response.json()["data"]["access_token"]

    response = await client.get(
        "/api/v1/audit-logs", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_old_one_stops_working(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    original_refresh_token = login_response.json()["data"]["refresh_token"]

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original_refresh_token}
    )
    assert refresh_response.status_code == 200
    new_refresh_token = refresh_response.json()["data"]["refresh_token"]
    assert new_refresh_token != original_refresh_token

    reuse_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original_refresh_token}
    )
    assert reuse_response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_reuse_detection_kills_the_whole_session(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    original_refresh_token = login_response.json()["data"]["refresh_token"]

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original_refresh_token}
    )
    rotated_refresh_token = refresh_response.json()["data"]["refresh_token"]

    # Replaying the already-rotated-out token is treated as theft, and
    # should invalidate the token it was rotated into as well.
    await client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh_token})

    still_valid_check = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated_refresh_token}
    )
    assert still_valid_check.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_token(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    refresh_token = login_response.json()["data"]["refresh_token"]

    logout_response = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}
    )
    assert logout_response.status_code == 204

    refresh_after_logout = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_login_is_rate_limited_after_repeated_failures(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    settings = get_settings()

    for _ in range(settings.login_rate_limit_attempts):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": REGISTER_PAYLOAD["email"], "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked_response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "wrong-password"},
    )
    assert blocked_response.status_code == 429


async def _promote_to_admin(session: AsyncSession, email: str) -> None:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    admin_role = (await session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    user.roles.append(admin_role)
    await session.flush()
