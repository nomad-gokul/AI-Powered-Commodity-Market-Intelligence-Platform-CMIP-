"""GraphService: the API-facing lifecycle for graph build runs - trigger
a rebuild (enqueued to the worker, same async-job pattern as extraction/
validate), and read a build run's status/stats. Mirrors
TrustPipelineService's role exactly: the service the API talks to,
never the one that does the actual computation (that's
GraphBuilderService, run by the worker - see builder_service.py).
"""

import uuid

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit.service import AuditService
from app.modules.extraction.repository import ExtractionRunRepository
from app.modules.graph.models import GraphBuildRun
from app.modules.graph.queue import JobQueue
from app.modules.graph.repository import GraphBuildRunRepository


class GraphService:
    def __init__(
        self,
        *,
        extraction_run_repo: ExtractionRunRepository,
        build_run_repo: GraphBuildRunRepository,
        audit_service: AuditService,
        job_queue: JobQueue,
    ) -> None:
        self.extraction_run_repo = extraction_run_repo
        self.build_run_repo = build_run_repo
        self.audit_service = audit_service
        self.job_queue = job_queue

    async def trigger_rebuild(
        self, *, extraction_run_id: uuid.UUID | None, requested_by: uuid.UUID
    ) -> GraphBuildRun:
        if extraction_run_id is not None:
            extraction_run = await self.extraction_run_repo.get_by_id(extraction_run_id)
            if extraction_run is None:
                raise NotFoundError(f"Extraction run {extraction_run_id} not found")

        active = await self.build_run_repo.get_active()
        if active is not None:
            raise ConflictError(
                f"A graph build is already in progress (build run {active.id}) - "
                "the graph is a single shared structure, so only one rebuild may run at a time"
            )

        run = await self.build_run_repo.create(GraphBuildRun(extraction_run_id=extraction_run_id))
        await self.audit_service.record(
            user_id=requested_by,
            action="graph.rebuild_requested",
            resource_type="graph_build_run",
            resource_id=run.id,
            metadata={"extraction_run_id": str(extraction_run_id) if extraction_run_id else "all"},
        )
        await self.job_queue.enqueue_job("run_graph_rebuild", str(run.id))
        return run

    async def get_build_run(self, build_run_id: uuid.UUID) -> GraphBuildRun:
        run = await self.build_run_repo.get_by_id(build_run_id)
        if run is None:
            raise NotFoundError(f"Graph build run {build_run_id} not found")
        return run

    async def list_build_runs(
        self, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[GraphBuildRun], int]:
        runs = await self.build_run_repo.list_recent(offset=offset, limit=limit)
        total = await self.build_run_repo.count_recent()
        return runs, total
