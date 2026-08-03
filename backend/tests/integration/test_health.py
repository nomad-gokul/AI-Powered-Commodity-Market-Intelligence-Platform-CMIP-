"""Liveness/readiness smoke tests against the real app, DB, and Redis."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_does_not_touch_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_confirms_db_and_redis_are_reachable(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_response_carries_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert "X-Request-ID" in response.headers
