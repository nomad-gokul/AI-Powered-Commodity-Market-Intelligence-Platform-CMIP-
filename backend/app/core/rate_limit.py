"""Redis-backed fixed-window rate limiter.

Applied per-route via the `rate_limit(...)` dependency factory, keyed by
client IP + a route-specific prefix. This is deliberately a simple fixed
window (INCR + EXPIRE), not a sliding-window/token-bucket - Phase 1 only
needs to blunt brute-force login attempts, and a fixed window is the
cheapest correct primitive for that. Revisit if per-plan/per-API-key
limiting is needed later; that's a product decision, not a Phase 1 one.

This is one of two rate-limiting layers in the target architecture: this
app-level limiter is business-rule-aware (keyed by route/user), while a
coarse IP-based limit at the Nginx layer (added in the hardening phase)
protects the whole stack, including routes that never reach this code.
"""

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import cast

import redis.asyncio as redis
from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError


@lru_cache
def get_redis_client() -> redis.Redis:
    settings = get_settings()
    # redis-py's from_url() resolves to an untyped Any under strict mypy
    # (its overloads don't narrow on decode_responses) - cast documents the
    # actual runtime type rather than silencing the check blindly.
    return cast(
        redis.Redis, redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
    )


class RateLimiter:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def check(self, key: str, max_attempts: int, window_seconds: int) -> None:
        count = await self._client.incr(key)
        if count == 1:
            await self._client.expire(key, window_seconds)
        if count > max_attempts:
            raise RateLimitExceededError(
                "Too many attempts. Try again in a moment.",
                details={
                    "key": key,
                    "max_attempts": max_attempts,
                    "window_seconds": window_seconds,
                },
            )


def rate_limit(
    key_prefix: str, max_attempts: int, window_seconds: int
) -> Callable[[Request], Awaitable[None]]:
    """Dependency factory: `Depends(rate_limit("login", 5, 60))`."""

    async def dependency(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        limiter = RateLimiter(get_redis_client())
        await limiter.check(f"ratelimit:{key_prefix}:{client_host}", max_attempts, window_seconds)

    return dependency
