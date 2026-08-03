"""Integration test fixtures: a real Postgres connection, wrapped in a
transaction that's rolled back after every test so tests never leave data
behind in the dev database, plus an httpx client wired to that same
transaction via a get_db_session override.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.database import engine, get_db_session
from app.core.rate_limit import get_redis_client
from app.main import app, lifespan
from app.modules.documents.storage.factory import get_storage_provider


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await outer_transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=app)
    try:
        # ASGITransport doesn't drive the ASGI lifespan protocol the way a
        # real server does, but app.state.arq_pool (needed by the documents
        # module's upload/reprocess routes) is only created in
        # app.main.lifespan's startup - so it's driven explicitly here.
        async with (
            lifespan(app),
            AsyncClient(transport=transport, base_url="http://test") as async_client,
        ):
            yield async_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest_asyncio.fixture(autouse=True)
async def _clean_redis() -> AsyncIterator[None]:
    """The rate limiter's keys live in Redis, not Postgres, so they aren't
    covered by db_session's transaction rollback. Every test's login
    attempts share the same client-IP key under ASGITransport (no real
    client address), so without this, rate-limit state would leak between
    tests and cause unrelated tests to start failing with 429s."""
    redis_client = get_redis_client()
    await redis_client.flushdb()
    yield
    await redis_client.flushdb()


@pytest.fixture(autouse=True)
def _isolated_document_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploads made during integration tests would otherwise land in the
    real STORAGE_LOCAL_ROOT on disk with no cleanup - redirect to a
    per-test tmp_path instead. get_storage_provider is @lru_cache'd, so
    the cache is cleared before and after so it rebuilds against the
    patched root and doesn't leak into later tests."""
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_local_root", str(tmp_path))
    get_storage_provider.cache_clear()
    yield
    get_storage_provider.cache_clear()


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """bcrypt's default rounds make every password test slow; drop rounds
    for the test suite only. Production config is untouched."""
    from passlib.context import CryptContext

    import app.core.security as security_module

    monkeypatch.setattr(
        security_module,
        "_pwd_context",
        CryptContext(schemes=["bcrypt"], bcrypt__rounds=4, deprecated="auto"),
    )
