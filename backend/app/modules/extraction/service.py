"""ExtractionService: trigger a new extraction run (its own lifecycle,
independent of document ingestion - see docs/ARCHITECTURE.md), read run
status, and list a document's entities/tables from its most recent run.
"""

import uuid

from ai_service.prompts.registry import PromptRegistry

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit.service import AuditService
from app.modules.documents.repository import DocumentChunkRepository, DocumentRepository
from app.modules.extraction.domain import compute_extraction_fingerprint
from app.modules.extraction.models import (
    ExtractedEntity,
    ExtractedTable,
    ExtractionRun,
    ExtractionStatus,
    TableCell,
)
from app.modules.extraction.queue import JobQueue
from app.modules.extraction.repository import (
    ExtractedEntityRepository,
    ExtractedTableRepository,
    ExtractionRunRepository,
    TableCellRepository,
)

PIPELINE_VERSION = "3.2.0"

_ACTIVE_STATUSES = (ExtractionStatus.PENDING, ExtractionStatus.RUNNING)


class ExtractionService:
    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        chunk_repo: DocumentChunkRepository,
        run_repo: ExtractionRunRepository,
        entity_repo: ExtractedEntityRepository,
        table_repo: ExtractedTableRepository,
        cell_repo: TableCellRepository,
        audit_service: AuditService,
        job_queue: JobQueue,
        prompt_registry: PromptRegistry,
        provider: str,
        model: str,
    ) -> None:
        self.document_repo = document_repo
        self.chunk_repo = chunk_repo
        self.run_repo = run_repo
        self.entity_repo = entity_repo
        self.table_repo = table_repo
        self.cell_repo = cell_repo
        self.audit_service = audit_service
        self.job_queue = job_queue
        self.prompt_registry = prompt_registry
        self.provider = provider
        self.model = model

    async def trigger_extraction(
        self, document_id: uuid.UUID, *, requested_by: uuid.UUID
    ) -> ExtractionRun:
        document = await self.document_repo.get_active_by_id(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")

        existing_runs = await self.run_repo.list_for_document(document_id)
        if any(run.status in _ACTIVE_STATUSES for run in existing_runs):
            raise ConflictError("An extraction run is already in progress for this document")

        chunk_count = await self.chunk_repo.count_for_document(document_id)
        if chunk_count == 0:
            raise ConflictError("Document has no chunks yet - wait for ingestion to complete first")

        prompt = self.prompt_registry.get("document_understanding")
        prompt_hash = self.prompt_registry.compute_hash(prompt)
        fingerprint = compute_extraction_fingerprint(
            document_hash=document.sha256_hash,
            prompt_hash=prompt_hash,
            pipeline_version=PIPELINE_VERSION,
            provider=self.provider,
            model=self.model,
        )

        existing_completed = await self.run_repo.find_completed_by_fingerprint(fingerprint)
        if existing_completed is not None:
            # An identical extraction (same document content, same
            # prompts, same pipeline version, same provider/model) already
            # completed - skip re-running the LLM pipeline and hand back
            # that result instead of enqueuing new work.
            return existing_completed

        run = await self.run_repo.create(
            ExtractionRun(
                document_id=document_id,
                pipeline_version=PIPELINE_VERSION,
                provider=self.provider,
                model=self.model,
                prompt_version=str(prompt.version),
                prompt_hash=prompt_hash,
                extraction_fingerprint=fingerprint,
                status=ExtractionStatus.PENDING,
            )
        )
        await self.audit_service.record(
            user_id=requested_by,
            action="document.extraction_requested",
            resource_type="document",
            resource_id=document_id,
            metadata={"extraction_run_id": str(run.id)},
        )
        await self.job_queue.enqueue_job("run_extraction", str(document_id), str(run.id))
        return run

    async def get_run(self, extraction_run_id: uuid.UUID) -> ExtractionRun:
        run = await self.run_repo.get_by_id(extraction_run_id)
        if run is None:
            raise NotFoundError(f"Extraction run {extraction_run_id} not found")
        return run

    async def list_entities(
        self, document_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[ExtractedEntity], int]:
        entities = await self.entity_repo.list_for_document(document_id, offset=offset, limit=limit)
        total = await self.entity_repo.count_for_document(document_id)
        return entities, total

    async def list_tables(
        self, document_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[ExtractedTable], int]:
        tables = await self.table_repo.list_for_document(document_id, offset=offset, limit=limit)
        total = await self.table_repo.count_for_document(document_id)
        return tables, total

    async def get_table(self, table_id: uuid.UUID) -> ExtractedTable:
        table = await self.table_repo.get_by_id(table_id)
        if table is None:
            raise NotFoundError(f"Table {table_id} not found")
        return table

    async def list_cells(self, table_id: uuid.UUID) -> list[TableCell]:
        return await self.cell_repo.list_for_table(table_id)
