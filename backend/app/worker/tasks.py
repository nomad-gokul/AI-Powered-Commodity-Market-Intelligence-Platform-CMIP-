"""The document ingestion pipeline, run as an ARQ background job.

Upload Complete -> Read File -> Determine OCR Requirement -> Text Extraction
-> Table Extraction -> Layout Extraction -> Metadata Extraction -> Chunk
Generation -> Persist Results -> Complete Job

Idempotent by construction: chunk persistence deletes-then-inserts (never
appends), and every status/progress field is overwritten, not incremented -
so re-running this task for the same document_id/job_id, whether via our
own retry-with-backoff or a user-triggered reprocess, converges to the same
end state instead of duplicating work.

Retry/backoff/dead-letter policy is owned here, not by ARQ's built-in
retry counter: job.retries/max_retries live in Postgres (survive a worker
restart, unlike ARQ's in-memory job_try) and are the only source of truth
for "try again" vs "give up." WorkerSettings.max_tries is set generously
high so ARQ's own ceiling never fires first - see worker/settings.py.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from arq.worker import Retry

from app.ai.engine.sequential import SequentialEngine
from app.ai.engine.types import AgentContext
from app.ai.providers.base import LLMUsage
from app.ai.providers.registry import get_provider_registry
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.metrics import (
    documents_processed_total,
    extraction_duration_seconds,
    job_retries_total,
    processing_duration_seconds,
    worker_failures_total,
)
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.service import AuditService
from app.modules.documents.models import (
    Document,
    DocumentChunk,
    JobStatus,
    ProcessingJob,
    ProcessingStatus,
)
from app.modules.documents.repository import (
    DocumentChunkRepository,
    DocumentRepository,
    ProcessingJobRepository,
)
from app.modules.extraction.agents.schemas import (
    DocumentUnderstandingAgentOutput,
    EntityExtractionAgentOutput,
    LayoutAgentOutput,
    TableExtractionAgentOutput,
)
from app.modules.extraction.domain import sum_usage
from app.modules.extraction.models import ExtractionRun, ExtractionStatus
from app.modules.extraction.pipeline import build_extraction_pipeline
from app.modules.extraction.repository import (
    EntityMentionRepository,
    ExtractedEntityRepository,
    ExtractedTableRepository,
    ExtractionRunRepository,
    TableCellRepository,
)
from app.modules.extraction.trust.agents.schemas import (
    ConfidenceAgentOutput,
    PersistTrustResultsOutput,
    ReviewQueueAgentOutput,
)
from app.modules.extraction.trust.models import TrustPipelineRun
from app.modules.extraction.trust.normalization.loader import get_canonical_registries
from app.modules.extraction.trust.pipeline import build_trust_pipeline
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
    ReviewQueueRepository,
    TrustPipelineRunRepository,
    ValidationResultRepository,
)
from app.modules.extraction.trust.rules.builtin import get_validation_rule_registry
from app.modules.graph.builder_service import (
    GraphBuilderService,
    GraphBuildPartialFailure,
    GraphBuildStats,
)
from app.modules.graph.models import GraphBuildRun
from app.modules.graph.repository import (
    GraphBuildRunRepository,
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
)
from app.modules.graph.rules.builtin import get_relationship_rule_registry

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".tiff"})


async def process_document(ctx: dict[str, Any], document_id: str, job_id: str) -> None:
    worker_id = str(ctx.get("job_id", "unknown-worker"))
    started = time.perf_counter()

    async with AsyncSessionLocal() as session:
        document_repo = DocumentRepository(session)
        job_repo = ProcessingJobRepository(session)
        chunk_repo = DocumentChunkRepository(session)
        audit_service = AuditService(AuditLogRepository(session))

        document = await document_repo.get_by_id(uuid.UUID(document_id))
        job = await job_repo.get_by_id(uuid.UUID(job_id))
        if document is None or job is None:
            logger.warning("process_document_missing_row", document_id=document_id, job_id=job_id)
            return

        job.status = JobStatus.RUNNING
        job.worker_id = worker_id
        job.started_at = datetime.now(UTC)
        await session.commit()

        try:
            await _run_pipeline(ctx, session, document, job, chunk_repo)
        except Exception as exc:  # noqa: BLE001 - deliberate pipeline-wide boundary, see module docstring
            await _handle_failure(document, job, audit_service, exc)
            await session.commit()
            if job.status is JobStatus.RETRYING:
                backoff = ctx["settings"].processing_retry_backoff_base_seconds * (2**job.retries)
                job_retries_total.labels(job_type=job.job_type.value).inc()
                raise Retry(defer=backoff) from exc
            return

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.execution_time_ms = int((time.perf_counter() - started) * 1000)
        job.progress = 100
        document.processing_status = ProcessingStatus.COMPLETED
        document.processing_progress = 100
        await session.commit()

        documents_processed_total.labels(status="completed").inc()
        processing_duration_seconds.observe(time.perf_counter() - started)


async def _run_pipeline(
    ctx: dict[str, Any],
    session: Any,
    document: Document,
    job: ProcessingJob,
    chunk_repo: DocumentChunkRepository,
) -> None:
    storage = ctx["storage"]
    is_image = document.extension in _IMAGE_EXTENSIONS

    await _advance(session, document, job, ProcessingStatus.PROCESSING, progress=10)
    file_bytes = await storage.download(document.storage_key)

    await _advance(session, document, job, ProcessingStatus.OCR, progress=25)
    extraction_start = time.perf_counter()
    if is_image:
        result = await ctx["image_extractor"].extract(file_bytes)
    else:
        result = await ctx["pdf_extractor"].extract(file_bytes)
    extraction_duration_seconds.observe(time.perf_counter() - extraction_start)

    await _advance(session, document, job, ProcessingStatus.EXTRACTING, progress=55)
    tables = [] if is_image else await asyncio.to_thread(ctx["table_extractor"].extract, file_bytes)
    tables_by_page: dict[int, list[list[list[str | None]]]] = {}
    for table in tables:
        tables_by_page.setdefault(table.page_number, []).append(table.rows)

    await _advance(session, document, job, ProcessingStatus.CHUNKING, progress=75)
    chunks = ctx["chunker"].chunk(result.pages)

    await chunk_repo.delete_for_document(document.id)
    chunk_rows = []
    for chunk in chunks:
        metadata = dict(chunk.metadata)
        page_tables = tables_by_page.get(chunk.page_number)
        if page_tables:
            metadata["tables"] = page_tables
        chunk_rows.append(
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                text=chunk.text,
                token_count=chunk.token_count,
                metadata_json=metadata,
            )
        )
    await chunk_repo.bulk_create(chunk_rows)

    if result.metadata is not None:
        document.language = result.metadata.language
        document.page_count = result.metadata.page_count
        document.metadata_json = {
            "title": result.metadata.title,
            "author": result.metadata.author,
            "creation_date": (
                result.metadata.creation_date.isoformat() if result.metadata.creation_date else None
            ),
            "word_count": result.metadata.word_count,
            "table_count": len(tables),
        }
    await session.flush()


async def _advance(
    session: Any, document: Document, job: ProcessingJob, stage: ProcessingStatus, *, progress: int
) -> None:
    document.processing_status = stage
    document.processing_progress = progress
    job.current_stage = stage
    job.progress = progress
    await session.commit()


async def _handle_failure(
    document: Document, job: ProcessingJob, audit_service: AuditService, exc: Exception
) -> None:
    logger.error(
        "document_processing_failed",
        document_id=str(document.id),
        job_id=str(job.id),
        error=str(exc),
    )
    job.retries += 1
    job.error_message = str(exc)[:2000]
    worker_failures_total.labels(job_type=job.job_type.value).inc()

    if job.retries < job.max_retries:
        job.status = JobStatus.RETRYING
        return

    job.status = JobStatus.FAILED
    job.failed_at = datetime.now(UTC)
    document.processing_status = ProcessingStatus.FAILED
    await audit_service.record(
        action="document.processing_dead_lettered",
        resource_type="document",
        resource_id=document.id,
        metadata={"job_id": str(job.id), "retries": job.retries, "error": str(exc)[:500]},
    )
    documents_processed_total.labels(status="failed").inc()


async def run_extraction(ctx: dict[str, Any], document_id: str, extraction_run_id: str) -> None:
    """The semantic extraction pipeline (Phase 3.2), run as an ARQ
    background job: Document Understanding -> Layout Analysis -> Entity
    Extraction -> Table Extraction -> Persist Results, via SequentialEngine.

    A separate job type from process_document with its own lifecycle -
    triggered explicitly via POST /documents/{id}/extract, independent of
    ingestion (see docs/ARCHITECTURE.md). No outer ARQ-level retry, unlike
    process_document: each LLM-calling step already retries transient
    failures at the LLMClient layer (Phase 3.1) and, for the two
    single-call steps, again at the EngineStep layer (see pipeline.py's
    module docstring) - a fully failed run is marked FAILED terminally and
    must be re-triggered explicitly, which creates a fresh extraction_run
    row rather than reusing this one.
    """
    started = time.perf_counter()

    async with AsyncSessionLocal() as session:
        run_repo = ExtractionRunRepository(session)
        document_repo = DocumentRepository(session)
        chunk_repo = DocumentChunkRepository(session)
        entity_repo = ExtractedEntityRepository(session)
        mention_repo = EntityMentionRepository(session)
        table_repo = ExtractedTableRepository(session)
        cell_repo = TableCellRepository(session)

        run = await run_repo.get_by_id(uuid.UUID(extraction_run_id))
        document = await document_repo.get_by_id(uuid.UUID(document_id))
        if run is None or document is None:
            logger.warning(
                "run_extraction_missing_row",
                document_id=document_id,
                extraction_run_id=extraction_run_id,
            )
            return

        run.status = ExtractionStatus.RUNNING
        run.started_at = datetime.now(UTC)
        await session.commit()

        if ctx.get("structured_output_service") is None:
            # build_worker_context() logs a warning and degrades to None
            # rather than crashing the whole worker when no LLM provider
            # is configured (see context.py) - but an individual
            # run_extraction job invoked in that state must fail with a
            # clear, actionable message, not a bare AttributeError three
            # layers down inside an agent.
            await _handle_extraction_failure(
                run,
                RuntimeError(
                    "No LLM provider is configured for this worker "
                    "(LLM_PROVIDER/API key missing) - extraction cannot run"
                ),
                retry_count=0,
            )
            await session.commit()
            worker_failures_total.labels(job_type="extraction").inc()
            return

        try:
            chunks = await chunk_repo.list_for_document(document.id)
            pdf_bytes = await ctx["storage"].download(document.storage_key)
            steps = build_extraction_pipeline(
                extraction_run_id=run.id,
                chunks=chunks,
                pdf_bytes=pdf_bytes,
                structured_output_service=ctx["structured_output_service"],
                prompt_registry=ctx["prompt_registry"],
                provider=run.provider,
                model=run.model,
                entity_repo=entity_repo,
                mention_repo=mention_repo,
                table_repo=table_repo,
                cell_repo=cell_repo,
            )
            engine_context = AgentContext(correlation_id=str(run.id))
            result = await SequentialEngine().run(steps, engine_context)
        except Exception as exc:  # noqa: BLE001 - deliberate pipeline-wide boundary, see docstring
            await _handle_extraction_failure(run, exc, retry_count=0)
            await session.commit()
            worker_failures_total.labels(job_type="extraction").inc()
            return

        retry_count = sum(step.retries_used for step in result.steps)
        if not result.succeeded:
            failure_reason = next(
                (step.error for step in result.steps if step.error), "unknown pipeline failure"
            )
            await _handle_extraction_failure(
                run, RuntimeError(failure_reason), retry_count=retry_count
            )
            await session.commit()
            worker_failures_total.labels(job_type="extraction").inc()
            return

        usage = _aggregate_usage(result)
        run.status = ExtractionStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.processing_time_ms = int((time.perf_counter() - started) * 1000)
        run.token_usage = usage.model_dump()
        run.estimated_cost = get_provider_registry().estimate_cost_usd(
            run.provider, run.model, usage
        )
        run.retry_count = retry_count
        run.metadata_json = {"layout_summary": _layout_summary(result)}
        await session.commit()


def _layout_summary(result: Any) -> dict[str, dict[str, Any]]:
    """A compact page_number -> {is_multi_column, column_count} summary of
    the layout step's output, persisted onto ExtractionRun.metadata_json
    (an existing, previously-unused column) so Phase 3.3's ConfidenceAgent
    has real layout data to score against without needing a new table -
    LayoutModel itself is otherwise only ever held in-memory for the
    duration of this pipeline run."""
    try:
        output = result.output_of("layout")
    except KeyError:
        return {}
    if not isinstance(output, LayoutAgentOutput):
        return {}
    return {
        str(page.page_number): {
            "is_multi_column": page.is_multi_column,
            "column_count": page.column_count,
        }
        for page in output.layout.pages
    }


def _usage_of(result: Any, step_name: str) -> LLMUsage | None:
    try:
        output = result.output_of(step_name)
    except KeyError:
        return None
    if isinstance(
        output,
        DocumentUnderstandingAgentOutput
        | LayoutAgentOutput
        | EntityExtractionAgentOutput
        | TableExtractionAgentOutput,
    ):
        return output.total_usage
    return None


def _aggregate_usage(result: Any) -> LLMUsage:
    """Sums total_usage across every LLM-calling step's output -
    PersistResults makes no LLM call and isn't included."""
    step_names = ("document_understanding", "layout", "entity_extraction", "table_extraction")
    usages = [usage for name in step_names if (usage := _usage_of(result, name)) is not None]
    return sum_usage(usages)


async def _handle_extraction_failure(
    run: ExtractionRun, exc: Exception, *, retry_count: int
) -> None:
    logger.error("extraction_failed", extraction_run_id=str(run.id), error=str(exc))
    run.status = ExtractionStatus.FAILED
    run.completed_at = datetime.now(UTC)
    run.error_message = str(exc)[:2000]
    run.retry_count = retry_count


async def run_trust_pipeline(
    ctx: dict[str, Any], extraction_run_id: str, trust_pipeline_run_id: str
) -> None:
    """The trust pipeline (Phase 3.3): Validation -> Normalization ->
    Confidence -> Review Queue -> Persist, via SequentialEngine.

    A separate job type and lifecycle from run_extraction - triggered via
    POST /extraction-runs/{id}/validate, only once that extraction run has
    already COMPLETED. Every step is deterministic (no LLM call - see
    app.modules.extraction.trust.agents' docstrings), so unlike
    run_extraction this task needs no structured_output_service/
    prompt_registry from ctx at all.
    """
    started = time.perf_counter()

    async with AsyncSessionLocal() as session:
        extraction_run_repo = ExtractionRunRepository(session)
        trust_run_repo = TrustPipelineRunRepository(session)
        entity_repo = ExtractedEntityRepository(session)
        table_repo = ExtractedTableRepository(session)
        cell_repo = TableCellRepository(session)
        validation_repo = ValidationResultRepository(session)
        confidence_repo = ConfidenceScoreRepository(session)
        normalization_repo = NormalizationResultRepository(session)
        review_queue_repo = ReviewQueueRepository(session)

        extraction_run = await extraction_run_repo.get_by_id(uuid.UUID(extraction_run_id))
        trust_run = await trust_run_repo.get_by_id(uuid.UUID(trust_pipeline_run_id))
        if extraction_run is None or trust_run is None:
            logger.warning(
                "run_trust_pipeline_missing_row",
                extraction_run_id=extraction_run_id,
                trust_pipeline_run_id=trust_pipeline_run_id,
            )
            return

        trust_run.status = ExtractionStatus.RUNNING
        trust_run.started_at = datetime.now(UTC)
        await session.commit()

        try:
            steps = build_trust_pipeline(
                extraction_run_id=extraction_run.id,
                extraction_run=extraction_run,
                entity_repo=entity_repo,
                table_repo=table_repo,
                cell_repo=cell_repo,
                validation_repo=validation_repo,
                confidence_repo=confidence_repo,
                normalization_repo=normalization_repo,
                review_queue_repo=review_queue_repo,
                rule_registry=get_validation_rule_registry(),
                canonical_registries=get_canonical_registries(),
            )
            engine_context = AgentContext(correlation_id=str(trust_run.id))
            result = await SequentialEngine().run(steps, engine_context)
        except Exception as exc:  # noqa: BLE001 - deliberate pipeline-wide boundary, see docstring
            await _handle_trust_pipeline_failure(trust_run, exc, retry_count=0)
            await session.commit()
            worker_failures_total.labels(job_type="trust_pipeline").inc()
            return

        retry_count = sum(step.retries_used for step in result.steps)
        if not result.succeeded:
            failure_reason = next(
                (step.error for step in result.steps if step.error), "unknown pipeline failure"
            )
            await _handle_trust_pipeline_failure(
                trust_run, RuntimeError(failure_reason), retry_count=retry_count
            )
            await session.commit()
            worker_failures_total.labels(job_type="trust_pipeline").inc()
            return

        trust_run.status = ExtractionStatus.COMPLETED
        trust_run.completed_at = datetime.now(UTC)
        trust_run.processing_time_ms = int((time.perf_counter() - started) * 1000)
        trust_run.retry_count = retry_count
        trust_run.entities_validated = _entity_count_validated(result)
        trust_run.entities_flagged_for_review = _entities_flagged(result)
        trust_run.average_confidence = _average_confidence(result)
        await session.commit()


def _entity_count_validated(result: Any) -> int:
    try:
        output = result.output_of("confidence")
    except KeyError:
        return 0
    return len(output.scores) if isinstance(output, ConfidenceAgentOutput) else 0


def _entities_flagged(result: Any) -> int:
    try:
        output = result.output_of("review_queue")
    except KeyError:
        return 0
    return len(output.entries) if isinstance(output, ReviewQueueAgentOutput) else 0


def _average_confidence(result: Any) -> float | None:
    try:
        output = result.output_of("persist_trust_results")
    except KeyError:
        return None
    return output.average_confidence if isinstance(output, PersistTrustResultsOutput) else None


async def _handle_trust_pipeline_failure(
    run: TrustPipelineRun, exc: Exception, *, retry_count: int
) -> None:
    logger.error("trust_pipeline_failed", trust_pipeline_run_id=str(run.id), error=str(exc))
    run.status = ExtractionStatus.FAILED
    run.completed_at = datetime.now(UTC)
    run.error_message = str(exc)[:2000]
    run.retry_count = retry_count


async def run_graph_rebuild(ctx: dict[str, Any], graph_build_run_id: str) -> None:
    """Phase 4's knowledge graph rebuild: either one extraction run's
    entities (graph_build_run.extraction_run_id set) or every extraction
    run with a COMPLETED trust pipeline run (a full-corpus sweep, when
    it's null), via GraphBuilderService.

    Delegates orchestration to GraphBuilderService rather than building
    the SequentialEngine pipeline inline the way run_trust_pipeline
    does: the Phase 4 spec names GraphBuilderService directly with this
    responsibility - see app.modules.graph.builder_service.
    """
    started = time.perf_counter()

    async with AsyncSessionLocal() as session:
        build_run_repo = GraphBuildRunRepository(session)
        builder_service = GraphBuilderService(
            entity_repo=ExtractedEntityRepository(session),
            mention_repo=EntityMentionRepository(session),
            chunk_repo=DocumentChunkRepository(session),
            extraction_run_repo=ExtractionRunRepository(session),
            normalization_repo=NormalizationResultRepository(session),
            confidence_repo=ConfidenceScoreRepository(session),
            node_repo=GraphNodeRepository(session),
            edge_repo=GraphEdgeRepository(session),
            evidence_repo=GraphEvidenceRepository(session),
            trust_run_repo=TrustPipelineRunRepository(session),
            rule_registry=get_relationship_rule_registry(),
        )

        build_run = await build_run_repo.get_by_id(uuid.UUID(graph_build_run_id))
        if build_run is None:
            logger.warning("run_graph_rebuild_missing_row", graph_build_run_id=graph_build_run_id)
            return

        build_run.status = ExtractionStatus.RUNNING
        build_run.started_at = datetime.now(UTC)
        await session.commit()

        try:
            if build_run.extraction_run_id is not None:
                output = await builder_service.build_for_extraction_run(build_run.extraction_run_id)
                stats = GraphBuildStats().add(output)
            else:
                stats = await builder_service.build_all()
        except GraphBuildPartialFailure as exc:
            _apply_graph_build_stats(build_run, exc.stats)
            await _handle_graph_build_failure(build_run, exc, retry_count=0)
            await session.commit()
            worker_failures_total.labels(job_type="graph_build").inc()
            return
        except Exception as exc:  # noqa: BLE001 - deliberate pipeline-wide boundary, see docstring
            await _handle_graph_build_failure(build_run, exc, retry_count=0)
            await session.commit()
            worker_failures_total.labels(job_type="graph_build").inc()
            return

        _apply_graph_build_stats(build_run, stats)
        build_run.status = ExtractionStatus.COMPLETED
        build_run.completed_at = datetime.now(UTC)
        build_run.processing_time_ms = int((time.perf_counter() - started) * 1000)
        await session.commit()


def _apply_graph_build_stats(build_run: GraphBuildRun, stats: GraphBuildStats) -> None:
    build_run.runs_processed = stats.runs_processed
    build_run.nodes_created = stats.nodes_created
    build_run.nodes_updated = stats.nodes_updated
    build_run.edges_created = stats.edges_created
    build_run.edges_updated = stats.edges_updated
    build_run.evidence_created = stats.evidence_created


async def _handle_graph_build_failure(
    build_run: GraphBuildRun, exc: Exception, *, retry_count: int
) -> None:
    logger.error("graph_build_failed", graph_build_run_id=str(build_run.id), error=str(exc))
    build_run.status = ExtractionStatus.FAILED
    build_run.completed_at = datetime.now(UTC)
    build_run.error_message = str(exc)[:2000]
    build_run.retry_count = retry_count
