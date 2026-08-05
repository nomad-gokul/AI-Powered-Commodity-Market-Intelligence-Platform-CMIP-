"""Pydantic API DTOs for the retrieval module.

Response payloads reuse shared.retrieval_contracts' DTOs directly
(Citation, RetrievalCandidate, RetrievalResultItem, RetrievalContext)
rather than redeclaring near-identical "Read" schemas - those DTOs were
already designed as the safe, curated external contract (never
embedding_vector, never raw GraphNode.metadata_json, no provider secrets -
see docs/ARCHITECTURE.md's Phase 5 section).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from shared.retrieval_contracts import RetrievalContext, RetrievalResultItem

from app.modules.retrieval.models import RetrievalRunStatus


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = None
    max_candidates: int | None = None
    graph_expansion_depth: int | None = None
    source_types: list[str] | None = None


class RetrieveGraphRequest(BaseModel):
    query: str = ""
    seed_canonical_ids: list[str] | None = None
    top_k: int | None = None
    depth: int | None = None


class RetrieveResponseData(BaseModel):
    retrieval_run_id: uuid.UUID
    results: list[RetrievalResultItem]


class RetrieveContextResponseData(BaseModel):
    retrieval_run_id: uuid.UUID
    context: RetrievalContext


class RetrievalRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query: str
    provider: str | None
    embedding_model: str | None
    reranker: str | None
    latency_ms: int | None
    total_candidates: int
    retrieved_results: int
    status: RetrievalRunStatus
    error_message: str | None
    requested_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RetrievalRunDetailRead(BaseModel):
    run: RetrievalRunRead
    results: list[RetrievalResultItem]
