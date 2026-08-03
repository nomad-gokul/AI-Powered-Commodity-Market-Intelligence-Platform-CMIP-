"""Pydantic API DTOs for the graph module. Read DTOs mirror their ORM
model 1:1 (model_config = ConfigDict(from_attributes=True), Pydantic v2
style) - same convention as trust/schemas.py."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.extraction.models import ExtractionStatus
from app.modules.graph.models import GraphNodeStatus


class GraphNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_id: str
    node_type: str
    display_name: str
    aliases_json: list[str]
    metadata_json: dict[str, Any]
    status: GraphNodeStatus
    merged_into_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class GraphEdgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    relationship_type: str
    confidence: float
    evidence_count: int
    provenance_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class GraphEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    edge_id: uuid.UUID
    document_id: uuid.UUID
    extraction_run_id: uuid.UUID
    entity_id: uuid.UUID
    page_number: int | None
    chunk_id: uuid.UUID | None
    prompt_hash: str
    created_at: datetime


class GraphBuildRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_run_id: uuid.UUID | None
    status: ExtractionStatus
    started_at: datetime | None
    completed_at: datetime | None
    processing_time_ms: int | None
    retry_count: int
    error_message: str | None
    runs_processed: int
    nodes_created: int
    nodes_updated: int
    edges_created: int
    edges_updated: int
    evidence_created: int
    created_at: datetime
    updated_at: datetime


class SubgraphRead(BaseModel):
    center: GraphNodeRead
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]


class PathRead(BaseModel):
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]


class GraphRebuildRequest(BaseModel):
    extraction_run_id: uuid.UUID | None = None


class GraphMergeRequest(BaseModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
