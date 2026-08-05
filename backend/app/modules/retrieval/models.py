"""ORM models for Phase 5's Knowledge Retrieval Platform: the polymorphic
embeddings table, and the retrieval_runs/retrieval_results run-tracking
pair that persists every hybrid-retrieval query for audit/observability -
the same "run" pattern as extraction_runs/trust_pipeline_runs/
graph_build_runs.

embeddings.source_id is a String, not a UUID FK, because it is
polymorphic: document chunks/graph nodes/graph edges have a real UUID
(stored as its string form), but canonical entities and ontology
definitions have no database row at all (CanonicalRegistry is static JSON
reference data; OntologyType/RelationshipType's natural key is a string) -
inventing a fake UUID for those would be dishonest. (source_type,
source_id) together identify what was embedded; there is deliberately no
FK constraint, the tradeoff any polymorphic-association table makes.

retrieval_runs.status/error_message/requested_by_user_id are additive
beyond Phase 5's literal column list, for the same reason
graph_nodes.status/merged_into_id were additive in Phase 4:
GET /retrieval-runs/{id} needs a status to be meaningful, and every other
"run" table in this codebase records who triggered it.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin
from app.modules.extraction.models import _values

EMBEDDING_DIMENSION = 1536
"""Must match ai_service.embeddings.models.EMBEDDING_DIMENSION - the fixed
pgvector column width, chosen to match the default provider's default
model (openai/text-embedding-3-small). Two independently declared
constants, same value, by the same design as AISettings/Settings
(Pre-Phase 5): backend's ORM layer must not import ai-service just for a
constant. See that module's docstring for the migration path to change
it."""


class EmbeddingSourceType(StrEnum):
    DOCUMENT_CHUNK = "document_chunk"
    GRAPH_NODE = "graph_node"
    GRAPH_EDGE = "graph_edge"
    CANONICAL_ENTITY = "canonical_entity"
    ONTOLOGY_DEFINITION = "ontology_definition"


class RetrievalRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RetrievalMethod(StrEnum):
    BM25 = "bm25"
    VECTOR = "vector"
    GRAPH_EXPANSION = "graph_expansion"
    HYBRID = "hybrid"


_embedding_source_type_enum = Enum(
    EmbeddingSourceType,
    name="embedding_source_type",
    values_callable=_values(EmbeddingSourceType),
)
_retrieval_result_source_type_enum = Enum(
    EmbeddingSourceType,
    name="retrieval_result_source_type",
    values_callable=_values(EmbeddingSourceType),
)
"""Same Python enum class as _embedding_source_type_enum, deliberately a
distinct native Postgres type - this table's migration lifecycle must
never share a DB type with an unrelated table, the same rule
graph/models.py's graph_build_status/extraction_status split follows."""

_retrieval_run_status_enum = Enum(
    RetrievalRunStatus, name="retrieval_run_status", values_callable=_values(RetrievalRunStatus)
)
_retrieval_method_enum = Enum(
    RetrievalMethod, name="retrieval_method", values_callable=_values(RetrievalMethod)
)


class Embedding(TimestampMixin, Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "embedding_provider",
            "embedding_model",
            name="uq_embeddings_source_provider_model",
        ),
        # HNSW built by default (better recall, no training step, pgvector's
        # own current recommendation); IVFFlat remains available on this
        # same column/table for a future migration to add if a workload
        # ever needs it - building both by default would be redundant
        # index maintenance cost for no benefit. Cosine is the query-time
        # default distance; L2 (<->) and inner product (<#>) remain usable
        # ad hoc via VectorSearch, just unindexed.
        Index(
            "ix_embeddings_vector_cosine_hnsw",
            "embedding_vector",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding_vector": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[EmbeddingSourceType] = mapped_column(
        _embedding_source_type_enum, nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)

    embedding_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # sha256 of the exact text embedded - EmbeddingService compares this
    # against a candidate's freshly-computed hash before ever calling the
    # provider, so identical content is never re-embedded.
    embedding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Typed Any rather than list[float]: pgvector-python returns a numpy
    # array on read by default, not a plain list - Any avoids a type lie
    # either direction without adding a numpy-specific import here.
    embedding_vector: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)


class RetrievalRun(TimestampMixin, Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reranker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieved_results: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[RetrievalRunStatus] = mapped_column(
        _retrieval_run_status_enum, nullable=False, default=RetrievalRunStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RetrievalResult(Base):
    """Write-once per run (no TimestampMixin/updated_at - a result row is
    never revised in place, matching graph_evidence's simpler shape)."""

    __tablename__ = "retrieval_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    retrieval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("retrieval_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[EmbeddingSourceType] = mapped_column(
        _retrieval_result_source_type_enum, nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    retrieval_method: Mapped[RetrievalMethod] = mapped_column(
        _retrieval_method_enum, nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
