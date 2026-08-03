"""ORM models for Phase 4's knowledge graph: nodes, edges, evidence, and
the ontology/relationship-type vocabulary they draw from - all built
from Phase 3.3's already-trusted, already-canonicalized entities, never
a new extraction of anything.

Unlike trust/, this module is NOT scoped to one extraction_run_id - a
graph node aggregates evidence for one canonical_id across every
document and run in the corpus, so its "run" record (graph_build_runs)
tracks a rebuild job, not a per-document pipeline execution, and its
fact tables (graph_edges, graph_evidence) are cumulative rather than
delete-then-replaced on every run - see repository.py/builder_service.py
for the upsert logic this implies.

graph_build_runs is one table beyond the five the spec names (graph_nodes,
graph_edges, graph_evidence, ontology_types, relationship_types): it is
the "run" record POST /graph/rebuild needs for the same reason
trust_pipeline_runs exists for Phase 3.3 - the endpoint enqueues work on
the ARQ worker and something has to be polled for status/stats.

graph_nodes.status/merged_into_id are additive beyond the spec's literal
field list, required to implement the confirmed tombstone-and-redirect
merge strategy: POST /graph/merge absorbs a duplicate node into its
survivor without ever deleting the row or losing the fact a merge
happened.

ontology_types/relationship_types have no created_at/updated_at,
matching the spec's own field lists for them - they are seed/reference
data (see alembic data migration), not events with a meaningful
insertion order.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin
from app.modules.extraction.models import ExtractionStatus, _values


class GraphNodeStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"


_graph_node_status_enum = Enum(
    GraphNodeStatus, name="graph_node_status", values_callable=_values(GraphNodeStatus)
)
_graph_build_status_enum = Enum(
    ExtractionStatus,
    name="graph_build_status",
    values_callable=_values(ExtractionStatus),
)
"""Reuses ExtractionStatus's Python values (pending/running/completed/failed
means the same thing here) but as its own native Postgres enum type, for
the same reason trust_pipeline_status is separate from extraction_status -
this table's migration lifecycle must never share a DB type with an
unrelated table."""


class OntologyType(Base):
    """The vocabulary of node types a GraphNode may declare - the
    identity-bearing subset of extraction's EntityType (company, port,
    country, commodity, contract, terminal, vessel, organization).
    Measurement/attribute types (currency, price, date, quantity, unit,
    incoterm, hs_code) are deliberately excluded: they describe a node,
    they are never themselves a node in a business relationship graph.
    """

    __tablename__ = "ontology_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parent_type: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("ontology_types.entity_type", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class RelationshipType(Base):
    """The vocabulary of relationship types a GraphEdge may declare, and
    their algebraic properties (symmetric/transitive) - consumed by
    KnowledgeGraphService's traversal logic, e.g. deciding whether
    following an edge backwards is meaningful.
    """

    __tablename__ = "relationship_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    relationship_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    inverse_relationship: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("relationship_types.relationship_name", ondelete="SET NULL"),
        nullable=True,
    )
    symmetric: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class GraphNode(TimestampMixin, Base):
    __tablename__ = "graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Phase 3.3's NormalizationResult.canonical_id - a node only exists
    # once an entity has been resolved to a canonical identity. Unique:
    # every real-world entity gets exactly one node, merged aliases and
    # all.
    canonical_id: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    node_type: Mapped[str] = mapped_column(
        String(64), ForeignKey("ontology_types.entity_type", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[GraphNodeStatus] = mapped_column(
        _graph_node_status_enum, nullable=False, default=GraphNodeStatus.ACTIVE
    )
    # Set when POST /graph/merge tombstones this node into a survivor.
    # Self-referential rather than a delete: preserves the fact a merge
    # happened, and lets any edge/evidence still pointing at this row's
    # id (never rewritten) be resolved to the live node by following this
    # pointer - see repository.py's resolve_active_node.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="SET NULL"), nullable=True
    )


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "relationship_type",
            name="uq_graph_edges_source_target_relationship",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("relationship_types.relationship_name", ondelete="RESTRICT"),
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A summary snapshot of the most recent contributing run
    # ({"latest_document_id", "latest_extraction_run_id",
    # "pipeline_version"}) - the itemized, per-mention trail lives in
    # graph_evidence; this is the cheap "who touched this edge last"
    # answer without a join.
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
    # Additive beyond the spec's literal field list: unlike trust's
    # fact tables, an edge is NOT append-only - rebuilding folds new
    # evidence into the same row (confidence/evidence_count change in
    # place), so "when was this edge last touched" is a real question.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
        nullable=False,
    )


class GraphEvidence(Base):
    """One row per (edge, entity mention) pair that justified an edge.

    The spec's field list gives a single `entity_id` column, but a
    relationship connects two entities - resolved by writing two rows per
    detected relationship instance (one for the source-side entity, one
    for the target-side), sharing edge_id/document_id/extraction_run_id/
    chunk_id/prompt_hash. This satisfies the literal schema without
    adding columns, and doubles as the natural "which entity mentions
    support this edge" query.
    """

    __tablename__ = "graph_evidence"
    __table_args__ = (
        UniqueConstraint(
            "edge_id", "entity_id", "chunk_id", name="uq_graph_evidence_edge_entity_chunk"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_edges.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class GraphBuildRun(TimestampMixin, Base):
    __tablename__ = "graph_build_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Null = full-corpus rebuild; set = rebuild scoped to one extraction
    # run's entities only (still upserted against the whole graph).
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[ExtractionStatus] = mapped_column(
        _graph_build_status_enum, nullable=False, default=ExtractionStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    runs_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edges_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edges_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
