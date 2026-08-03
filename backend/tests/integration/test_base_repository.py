"""Integration tests for BaseRepository's generic CRUD primitives, exercised
through RoleRepository (a plain subclass with no method overrides) against
the real database."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role
from app.modules.auth.repository import RoleRepository


@pytest.mark.asyncio
async def test_create_and_get_by_id(db_session: AsyncSession) -> None:
    repo = RoleRepository(db_session)
    created = await repo.create(Role(name="ops", permissions=["ops:read"]))

    fetched = await repo.get_by_id(created.id)

    assert fetched is not None
    assert fetched.name == "ops"


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing_row(db_session: AsyncSession) -> None:
    repo = RoleRepository(db_session)
    assert await repo.get_by_id(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_list_orders_by_created_at_descending(db_session: AsyncSession) -> None:
    repo = RoleRepository(db_session)
    first = await repo.create(Role(name="role-a", permissions=[]))
    second = await repo.create(Role(name="role-b", permissions=[]))

    roles = await repo.list(limit=100)

    names = [r.name for r in roles]
    assert names.index("role-b") < names.index("role-a")
    assert first.id != second.id  # sanity: two distinct rows were created


@pytest.mark.asyncio
async def test_count_reflects_created_rows(db_session: AsyncSession) -> None:
    repo = RoleRepository(db_session)
    before = await repo.count()
    await repo.create(Role(name="role-c", permissions=[]))

    after = await repo.count()

    assert after == before + 1


@pytest.mark.asyncio
async def test_update_persists_field_changes(db_session: AsyncSession) -> None:
    repo = RoleRepository(db_session)
    role = await repo.create(Role(name="role-d", description="old", permissions=[]))

    updated = await repo.update(role, description="new")

    assert updated.description == "new"
    refetched = await repo.get_by_id(role.id)
    assert refetched is not None
    assert refetched.description == "new"


@pytest.mark.asyncio
async def test_delete_removes_the_row(db_session: AsyncSession) -> None:
    repo = RoleRepository(db_session)
    role = await repo.create(Role(name="role-e", permissions=[]))

    await repo.delete(role)

    assert await repo.get_by_id(role.id) is None
