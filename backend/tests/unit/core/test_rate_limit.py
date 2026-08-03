"""Unit tests for the fixed-window RateLimiter, against an in-memory fake
Redis client (no network/Docker dependency for this test)."""

import pytest

from app.core.exceptions import RateLimitExceededError
from app.core.rate_limit import RateLimiter


class FakeRedis:
    """Just enough of the redis.asyncio interface for RateLimiter.check."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        pass  # TTL behavior isn't exercised by these tests


@pytest.mark.asyncio
async def test_allows_requests_under_the_limit() -> None:
    limiter = RateLimiter(FakeRedis())
    for _ in range(5):
        await limiter.check("login:1.2.3.4", max_attempts=5, window_seconds=60)  # must not raise


@pytest.mark.asyncio
async def test_blocks_requests_over_the_limit() -> None:
    limiter = RateLimiter(FakeRedis())
    for _ in range(5):
        await limiter.check("login:1.2.3.4", max_attempts=5, window_seconds=60)

    with pytest.raises(RateLimitExceededError):
        await limiter.check("login:1.2.3.4", max_attempts=5, window_seconds=60)


@pytest.mark.asyncio
async def test_different_keys_have_independent_limits() -> None:
    limiter = RateLimiter(FakeRedis())
    for _ in range(5):
        await limiter.check("login:1.2.3.4", max_attempts=5, window_seconds=60)

    await limiter.check("login:5.6.7.8", max_attempts=5, window_seconds=60)  # must not raise
