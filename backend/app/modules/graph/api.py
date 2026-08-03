"""HTTP routes for the knowledge graph: triggering/reading rebuild runs,
and reading/traversing/merging the graph itself.

Unlike trust (which reuses extraction's permissions), the graph is a
genuinely new resource with a genuinely new actor capability (rebuilding
and correcting a corpus-wide structure, not just triggering one run's
pipeline) - so this phase adds its own permissions, graph:read and
graph:rebuild, granted to the same roles extraction:read/extraction:trigger
are (see the accompanying Alembic data migration).
"""

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import ApiResponse, PageMeta, PaginatedResponse
from app.core.database import get_db_session
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import get_current_user, require_permission
from app.modules.auth.models import User
from app.modules.extraction.repository import ExtractionRunRepository
from app.modules.graph.models import GraphNodeStatus
from app.modules.graph.query_service import KnowledgeGraphService
from app.modules.graph.queue import JobQueue
from app.modules.graph.repository import (
    GraphBuildRunRepository,
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
)
from app.modules.graph.schemas import (
    GraphBuildRunRead,
    GraphEdgeRead,
    GraphEvidenceRead,
    GraphMergeRequest,
    GraphNodeRead,
    GraphRebuildRequest,
    PathRead,
    SubgraphRead,
)
from app.modules.graph.service import GraphService

graph_router = APIRouter(prefix="/graph", tags=["Graph"])
graph_nodes_router = APIRouter(prefix="/graph/nodes", tags=["Graph"])
graph_edges_router = APIRouter(prefix="/graph/edges", tags=["Graph"])
graph_entity_router = APIRouter(prefix="/graph/entity", tags=["Graph"])
graph_relationships_router = APIRouter(prefix="/graph/relationships", tags=["Graph"])


def get_graph_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> GraphService:
    job_queue: JobQueue = request.app.state.arq_pool
    return GraphService(
        extraction_run_repo=ExtractionRunRepository(session),
        build_run_repo=GraphBuildRunRepository(session),
        audit_service=AuditService(AuditLogRepository(session)),
        job_queue=job_queue,
    )


def get_knowledge_graph_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> KnowledgeGraphService:
    return KnowledgeGraphService(
        node_repo=GraphNodeRepository(session),
        edge_repo=GraphEdgeRepository(session),
        evidence_repo=GraphEvidenceRepository(session),
        audit_service=AuditService(AuditLogRepository(session)),
    )


def _page_meta(*, page: int, page_size: int, total: int) -> PageMeta:
    return PageMeta(
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=max(1, math.ceil(total / page_size)),
    )


# -- build lifecycle -------------------------------------------------------


@graph_router.post(
    "/rebuild",
    response_model=ApiResponse[GraphBuildRunRead],
    status_code=202,
    dependencies=[Depends(require_permission("graph:rebuild"))],
)
async def trigger_rebuild(
    body: GraphRebuildRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> ApiResponse[GraphBuildRunRead]:
    run = await service.trigger_rebuild(
        extraction_run_id=body.extraction_run_id, requested_by=current_user.id
    )
    return ApiResponse(data=GraphBuildRunRead.model_validate(run))


@graph_router.get(
    "/build-runs",
    response_model=PaginatedResponse[GraphBuildRunRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def list_build_runs(
    service: Annotated[GraphService, Depends(get_graph_service)],
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResponse[GraphBuildRunRead]:
    runs, total = await service.list_build_runs(offset=(page - 1) * page_size, limit=page_size)
    return PaginatedResponse(
        data=[GraphBuildRunRead.model_validate(r) for r in runs],
        meta=_page_meta(page=page, page_size=page_size, total=total),
    )


@graph_router.get(
    "/build-runs/{build_run_id}",
    response_model=ApiResponse[GraphBuildRunRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_build_run(
    build_run_id: uuid.UUID,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> ApiResponse[GraphBuildRunRead]:
    run = await service.get_build_run(build_run_id)
    return ApiResponse(data=GraphBuildRunRead.model_validate(run))


# -- merge -------------------------------------------------------------------


@graph_router.post(
    "/merge",
    response_model=ApiResponse[GraphNodeRead],
    dependencies=[Depends(require_permission("graph:rebuild"))],
)
async def merge_nodes(
    body: GraphMergeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
) -> ApiResponse[GraphNodeRead]:
    node = await service.merge_nodes(
        body.source_node_id, body.target_node_id, requested_by=current_user.id
    )
    return ApiResponse(data=GraphNodeRead.model_validate(node))


# -- path ----------------------------------------------------------------


@graph_router.get(
    "/path",
    response_model=ApiResponse[PathRead | None],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def shortest_path(
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
    source_canonical_id: str,
    target_canonical_id: str,
    relationship_type: str | None = None,
) -> ApiResponse[PathRead | None]:
    result = await service.shortest_path(
        source_canonical_id, target_canonical_id, relationship_type=relationship_type
    )
    if result is None:
        return ApiResponse(data=None)
    return ApiResponse(
        data=PathRead(
            nodes=[GraphNodeRead.model_validate(n) for n in result.nodes],
            edges=[GraphEdgeRead.model_validate(e) for e in result.edges],
        )
    )


# -- nodes -------------------------------------------------------------------


@graph_nodes_router.get(
    "",
    response_model=PaginatedResponse[GraphNodeRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def list_nodes(
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
    node_type: str | None = None,
    status: GraphNodeStatus | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[GraphNodeRead]:
    nodes, total = await service.list_nodes(
        node_type=node_type, status=status, offset=(page - 1) * page_size, limit=page_size
    )
    return PaginatedResponse(
        data=[GraphNodeRead.model_validate(n) for n in nodes],
        meta=_page_meta(page=page, page_size=page_size, total=total),
    )


@graph_nodes_router.get(
    "/{node_id}",
    response_model=ApiResponse[GraphNodeRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_node(
    node_id: uuid.UUID,
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
) -> ApiResponse[GraphNodeRead]:
    node = await service.get_node(node_id)
    return ApiResponse(data=GraphNodeRead.model_validate(node))


@graph_nodes_router.get(
    "/{node_id}/neighbors",
    response_model=ApiResponse[list[GraphEdgeRead]],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_node_neighbors(
    node_id: uuid.UUID,
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
    relationship_type: str | None = None,
    limit: int = 50,
) -> ApiResponse[list[GraphEdgeRead]]:
    edges = await service.neighbors(node_id, relationship_type=relationship_type, limit=limit)
    return ApiResponse(data=[GraphEdgeRead.model_validate(e) for e in edges])


@graph_nodes_router.get(
    "/{node_id}/subgraph",
    response_model=ApiResponse[SubgraphRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_node_subgraph(
    node_id: uuid.UUID,
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
    depth: int = 2,
    relationship_type: str | None = None,
) -> ApiResponse[SubgraphRead]:
    result = await service.subgraph(node_id, depth=depth, relationship_type=relationship_type)
    return ApiResponse(
        data=SubgraphRead(
            center=GraphNodeRead.model_validate(result.center),
            nodes=[GraphNodeRead.model_validate(n) for n in result.nodes],
            edges=[GraphEdgeRead.model_validate(e) for e in result.edges],
        )
    )


# -- edges -------------------------------------------------------------------


@graph_edges_router.get(
    "",
    response_model=PaginatedResponse[GraphEdgeRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def list_edges(
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
    relationship_type: str | None = None,
    node_id: uuid.UUID | None = None,
    min_confidence: float | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[GraphEdgeRead]:
    edges, total = await service.list_edges(
        relationship_type=relationship_type,
        node_id=node_id,
        min_confidence=min_confidence,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return PaginatedResponse(
        data=[GraphEdgeRead.model_validate(e) for e in edges],
        meta=_page_meta(page=page, page_size=page_size, total=total),
    )


@graph_edges_router.get(
    "/{edge_id}",
    response_model=ApiResponse[GraphEdgeRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_edge(
    edge_id: uuid.UUID,
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
) -> ApiResponse[GraphEdgeRead]:
    edge = await service.get_edge(edge_id)
    return ApiResponse(data=GraphEdgeRead.model_validate(edge))


@graph_edges_router.get(
    "/{edge_id}/evidence",
    response_model=ApiResponse[list[GraphEvidenceRead]],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_edge_evidence(
    edge_id: uuid.UUID,
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
) -> ApiResponse[list[GraphEvidenceRead]]:
    evidence = await service.list_evidence_for_edge(edge_id)
    return ApiResponse(data=[GraphEvidenceRead.model_validate(e) for e in evidence])


# -- entity / relationships lookup --------------------------------------


@graph_entity_router.get(
    "/{canonical_id}",
    response_model=ApiResponse[GraphNodeRead],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_entity(
    canonical_id: str,
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
) -> ApiResponse[GraphNodeRead]:
    node = await service.get_node_by_canonical_id(canonical_id)
    return ApiResponse(data=GraphNodeRead.model_validate(node))


@graph_relationships_router.get(
    "/{canonical_id}",
    response_model=ApiResponse[list[GraphEdgeRead]],
    dependencies=[Depends(require_permission("graph:read"))],
)
async def get_relationships(
    canonical_id: str,
    service: Annotated[KnowledgeGraphService, Depends(get_knowledge_graph_service)],
    relationship_type: str | None = None,
) -> ApiResponse[list[GraphEdgeRead]]:
    edges = await service.relationships_for_canonical_id(
        canonical_id, relationship_type=relationship_type
    )
    return ApiResponse(data=[GraphEdgeRead.model_validate(e) for e in edges])
