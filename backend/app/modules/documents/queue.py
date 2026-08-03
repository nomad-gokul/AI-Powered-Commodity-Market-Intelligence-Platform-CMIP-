"""Structural interface for enqueuing background jobs.

DocumentService depends on this Protocol, not on arq.ArqRedis directly, so
unit tests can pass a plain AsyncMock instead of needing a live Redis
connection. The real arq.ArqRedis pool (created in app.main's lifespan)
satisfies this structurally - no adapter class needed.
"""

from typing import Protocol


class JobQueue(Protocol):
    async def enqueue_job(self, function: str, *args: object) -> object | None: ...
