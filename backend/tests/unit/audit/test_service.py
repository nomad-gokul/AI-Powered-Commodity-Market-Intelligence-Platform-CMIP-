"""Unit tests for AuditService, with the repository mocked."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.modules.audit.service import AuditService


@pytest.fixture
def service() -> tuple[AuditService, AsyncMock]:
    repo = AsyncMock()
    return AuditService(repo), repo


@pytest.mark.asyncio
async def test_record_persists_all_fields(service) -> None:
    audit_service, repo = service
    repo.create.side_effect = lambda entry: entry
    user_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    entry = await audit_service.record(
        action="user.login",
        resource_type="user",
        user_id=user_id,
        resource_id=resource_id,
        metadata={"method": "password"},
        ip_address="203.0.113.5",
    )

    assert entry.action == "user.login"
    assert entry.user_id == user_id
    assert entry.resource_id == resource_id
    assert entry.metadata_ == {"method": "password"}
    assert entry.ip_address == "203.0.113.5"


@pytest.mark.asyncio
async def test_record_defaults_metadata_to_empty_dict(service) -> None:
    audit_service, repo = service
    repo.create.side_effect = lambda entry: entry

    entry = await audit_service.record(action="user.login", resource_type="user")

    assert entry.metadata_ == {}


@pytest.mark.asyncio
async def test_search_delegates_to_repository_and_returns_total(service) -> None:
    audit_service, repo = service
    repo.search.return_value = ["entry-1", "entry-2"]
    repo.count.return_value = 2

    entries, total = await audit_service.search(action="user.login")

    assert entries == ["entry-1", "entry-2"]
    assert total == 2
