"""Integration tests for admin-only role/user management routes."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User

ADMIN_PAYLOAD = {
    "email": "admin@example.com",
    "full_name": "Admin User",
    "password": "a-genuinely-strong-password",
}


async def _register_and_login_as_admin(client: AsyncClient, db_session: AsyncSession) -> str:
    await client.post("/api/v1/auth/register", json=ADMIN_PAYLOAD)
    user = (
        await db_session.execute(select(User).where(User.email == ADMIN_PAYLOAD["email"]))
    ).scalar_one()
    admin_role = (await db_session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    user.roles.append(admin_role)
    await db_session.flush()

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_PAYLOAD["email"], "password": ADMIN_PAYLOAD["password"]},
    )
    return login_response.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_admin_can_create_and_list_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login_as_admin(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = await client.post(
        "/api/v1/roles",
        json={"name": "trader", "description": "Can view prices", "permissions": ["prices:read"]},
        headers=headers,
    )
    assert create_response.status_code == 201
    assert create_response.json()["data"]["name"] == "trader"

    list_response = await client.get("/api/v1/roles", headers=headers)
    assert list_response.status_code == 200
    role_names = {r["name"] for r in list_response.json()["data"]}
    assert {"admin", "analyst", "viewer", "trader"}.issubset(role_names)


@pytest.mark.asyncio
async def test_admin_cannot_create_duplicate_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login_as_admin(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/api/v1/roles", json={"name": "admin", "permissions": []}, headers=headers
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_non_admin_cannot_create_roles(client: AsyncClient) -> None:
    payload = {
        "email": "regular@example.com",
        "full_name": "Regular User",
        "password": "a-genuinely-strong-password",
    }
    await client.post("/api/v1/auth/register", json=payload)
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    token = login_response.json()["data"]["access_token"]

    response = await client.post(
        "/api/v1/roles",
        json={"name": "trader", "permissions": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_users_and_assign_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login_as_admin(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    other_payload = {
        "email": "newtrader@example.com",
        "full_name": "New Trader",
        "password": "a-genuinely-strong-password",
    }
    register_response = await client.post("/api/v1/auth/register", json=other_payload)
    other_user_id = register_response.json()["data"]["id"]

    list_response = await client.get("/api/v1/users", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["meta"]["total_items"] >= 2

    analyst_role_id = next(
        r["id"]
        for r in (await client.get("/api/v1/roles", headers=headers)).json()["data"]
        if r["name"] == "analyst"
    )

    assign_response = await client.post(
        f"/api/v1/users/{other_user_id}/roles",
        json={"role_id": analyst_role_id},
        headers=headers,
    )
    assert assign_response.status_code == 200
    role_names = {r["name"] for r in assign_response.json()["data"]["roles"]}
    assert "analyst" in role_names
