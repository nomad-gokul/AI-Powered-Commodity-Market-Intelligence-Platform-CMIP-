"""Builds the SequentialEngine pipeline for one extraction run:

Document Understanding -> Layout Analysis -> Entity Extraction ->
Table Extraction -> Persist Results

Retry policy: DocumentUnderstanding/Layout make exactly one LLM call each,
so a full EngineStep-level retry is cheap and given RetryPolicy(2).
EntityExtraction/TableExtraction make one LLM call per chunk/table
internally - LLMClient (Phase 3.1) already retries each individual call on
transient errors, and StructuredOutputService already retries invalid
schema responses, so a THIRD retry layer that re-runs the entire loop from
scratch on any failure would be expensive and mostly redundant; these get
RetryPolicy(1) (no engine-level retry) deliberately. PersistResults is
delete-then-insert scoped to its own extraction_run_id (idempotent), so it
safely gets RetryPolicy(2) too.
"""

import uuid

from ai_service.prompts.registry import PromptRegistry
from ai_service.structured.service import StructuredOutputService
from shared.agent_contracts import EngineStep, RetryPolicy

from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.document_understanding_agent import DocumentUnderstandingAgent
from app.modules.extraction.agents.entity_extraction_agent import EntityExtractionAgent
from app.modules.extraction.agents.layout_agent import LayoutAgent
from app.modules.extraction.agents.persist_results_agent import PersistResultsAgent
from app.modules.extraction.agents.table_extraction_agent import TableExtractionAgent
from app.modules.extraction.repository import (
    EntityMentionRepository,
    ExtractedEntityRepository,
    ExtractedTableRepository,
    TableCellRepository,
)

_SINGLE_CALL_RETRY_POLICY = RetryPolicy(
    max_attempts=2, backoff_base_seconds=2.0, backoff_multiplier=2.0
)
_LOOPING_CALL_RETRY_POLICY = RetryPolicy(max_attempts=1)
_PERSIST_RETRY_POLICY = RetryPolicy(max_attempts=2, backoff_base_seconds=1.0)

_SINGLE_CALL_TIMEOUT_SECONDS = 180.0
_LOOPING_CALL_TIMEOUT_SECONDS = 900.0
_PERSIST_TIMEOUT_SECONDS = 60.0


def build_extraction_pipeline(
    *,
    extraction_run_id: uuid.UUID,
    chunks: list[DocumentChunk],
    pdf_bytes: bytes,
    structured_output_service: StructuredOutputService,
    prompt_registry: PromptRegistry,
    provider: str,
    model: str,
    entity_repo: ExtractedEntityRepository,
    mention_repo: EntityMentionRepository,
    table_repo: ExtractedTableRepository,
    cell_repo: TableCellRepository,
) -> list[EngineStep]:
    document_understanding = DocumentUnderstandingAgent(
        structured_output_service=structured_output_service,
        prompt_registry=prompt_registry,
        model=model,
        chunks=chunks,
    )
    layout = LayoutAgent(
        structured_output_service=structured_output_service,
        prompt_registry=prompt_registry,
        model=model,
        pdf_bytes=pdf_bytes,
    )
    entity_extraction = EntityExtractionAgent(
        structured_output_service=structured_output_service,
        prompt_registry=prompt_registry,
        model=model,
        chunks=chunks,
    )
    table_extraction = TableExtractionAgent(
        structured_output_service=structured_output_service,
        prompt_registry=prompt_registry,
        model=model,
        chunks=chunks,
        pdf_bytes=pdf_bytes,
    )
    persist_results = PersistResultsAgent(
        extraction_run_id=extraction_run_id,
        entity_repo=entity_repo,
        mention_repo=mention_repo,
        table_repo=table_repo,
        cell_repo=cell_repo,
        chunks=chunks,
        provider=provider,
        model=model,
        entity_prompt_version=str(prompt_registry.get("entity_extraction").version),
        table_prompt_version=str(prompt_registry.get("table_extraction").version),
    )

    return [
        EngineStep(
            agent=document_understanding,
            retry_policy=_SINGLE_CALL_RETRY_POLICY,
            timeout_seconds=_SINGLE_CALL_TIMEOUT_SECONDS,
        ),
        EngineStep(
            agent=layout,
            retry_policy=_SINGLE_CALL_RETRY_POLICY,
            timeout_seconds=_SINGLE_CALL_TIMEOUT_SECONDS,
        ),
        EngineStep(
            agent=entity_extraction,
            retry_policy=_LOOPING_CALL_RETRY_POLICY,
            timeout_seconds=_LOOPING_CALL_TIMEOUT_SECONDS,
        ),
        EngineStep(
            agent=table_extraction,
            retry_policy=_LOOPING_CALL_RETRY_POLICY,
            timeout_seconds=_LOOPING_CALL_TIMEOUT_SECONDS,
        ),
        EngineStep(
            agent=persist_results,
            retry_policy=_PERSIST_RETRY_POLICY,
            timeout_seconds=_PERSIST_TIMEOUT_SECONDS,
        ),
    ]
