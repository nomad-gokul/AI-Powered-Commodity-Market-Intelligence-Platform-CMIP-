"""Structural interface for enqueuing background jobs - identical shape to
app.modules.documents.queue.JobQueue. Duplicated rather than imported: a
Protocol is structurally typed, so arq.ArqRedis satisfies both without
either module depending on the other (see the cross-module dependency
rule in docs/ARCHITECTURE.md - modules don't reach into each other for
non-repository concerns)."""

from typing import Protocol


class JobQueue(Protocol):
    async def enqueue_job(self, function: str, *args: object) -> object | None: ...
