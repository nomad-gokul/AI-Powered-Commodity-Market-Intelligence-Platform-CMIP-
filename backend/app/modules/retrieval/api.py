"""HTTP routes for Phase 5's Knowledge Retrieval Platform: hybrid
retrieval, structured context assembly, graph-only retrieval, and reading
back a persisted retrieval run.

Retrieval is a read-only capability from the caller's perspective, even
though it performs real computation (BM25 + vector search + graph
expansion) and persists a RetrievalRun as a side effect - the same
precedent graph:read set for subgraph/neighbors traversal (see
app/modules/graph/api.py's docstring). No separate "trigger" verb: unlike
extraction/trust/graph, there is nothing here to irreversibly mutate
business data, so viewer and analyst get an identical grant (see the
accompanying Alembic data migration).
"""

import uuid
from typing import Annotated

from ai_service.context.builder import get_context_builder
from ai_service.embeddings.base import EmbeddingProvider
from ai_service.embeddings.factory import get_embedding_provider
from ai_service.retrieval.reranker import get_reranker_service
from fastapi import APIRouter, Depends
from shared.ai_exceptions import ConfigurationError
from shared.retrieval_contracts import RetrievalCandidate, RetrievalResultItem
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import ApiResponse
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import get_current_user, require_permission
from app.modules.auth.models import User
from app.modules.documents.repository import DocumentChunkRepository, DocumentRepository
from app.modules.extraction.trust.normalization.canonical_registry import CanonicalRegistry
from app.modules.extraction.trust.normalization.loader import get_canonical_registries
from app.modules.graph.query_service import KnowledgeGraphService
from app.modules.graph.repository import (
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
    OntologyTypeRepository,
)
from app.modules.retrieval.bm25 import BM25Search
from app.modules.retrieval.citation_engine import CitationEngine
from app.modules.retrieval.context_service import ContextService
from app.modules.retrieval.graph_expansion import GraphExpansion
from app.modules.retrieval.hybrid_retriever import HybridRetrievalRequest, HybridRetriever
from app.modules.retrieval.models import EmbeddingSourceType
from app.modules.retrieval.query_analyzer import QueryAnalyzer, build_company_registry
from app.modules.retrieval.repository import RetrievalResultRepository, RetrievalRunRepository
from app.modules.retrieval.schemas import (
    RetrievalRunDetailRead,
    RetrievalRunRead,
    RetrieveContextResponseData,
    RetrieveGraphRequest,
    RetrieveRequest,
    RetrieveResponseData,
)
from app.modules.retrieval.vector_search import VectorSearch

retrieval_router = APIRouter(prefix="/retrieve", tags=["Retrieval"])
retrieval_runs_router = APIRouter(prefix="/retrieval-runs", tags=["Retrieval"])


# -- dependency providers -----------------------------------------------------
#
# get_company_registry queries every graph_nodes row of node_type=company
# (no pagination - detecting a company mention needs the whole alias
# universe, not one page of it). 10_000 is a pragmatic, disclosed cap for
# this phase's corpus size, not a hard architectural limit - see
# docs/ARCHITECTURE.md's Phase 5 section. FastAPI caches this dependency's
# result per request, so it is computed once even though both
# get_query_analyzer and get_context_service depend on it.

_COMPANY_REGISTRY_SCAN_LIMIT = 10_000


async def get_company_registry(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CanonicalRegistry:
    node_repo = GraphNodeRepository(session)
    company_nodes = await node_repo.list_nodes(
        node_type="company", limit=_COMPANY_REGISTRY_SCAN_LIMIT
    )
    return build_company_registry(company_nodes)


def get_query_analyzer(
    companies: Annotated[CanonicalRegistry, Depends(get_company_registry)],
) -> QueryAnalyzer:
    return QueryAnalyzer(registries=get_canonical_registries(), companies=companies)


def get_citation_engine(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CitationEngine:
    return CitationEngine(
        document_repo=DocumentRepository(session),
        chunk_repo=DocumentChunkRepository(session),
        node_repo=GraphNodeRepository(session),
        edge_repo=GraphEdgeRepository(session),
        evidence_repo=GraphEvidenceRepository(session),
    )


def get_context_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    companies: Annotated[CanonicalRegistry, Depends(get_company_registry)],
    citation_engine: Annotated[CitationEngine, Depends(get_citation_engine)],
) -> ContextService:
    return ContextService(
        chunk_repo=DocumentChunkRepository(session),
        node_repo=GraphNodeRepository(session),
        edge_repo=GraphEdgeRepository(session),
        ontology_repo=OntologyTypeRepository(session),
        citation_engine=citation_engine,
        context_builder=get_context_builder(),
        registries=get_canonical_registries(),
        companies=companies,
    )


def get_hybrid_retriever(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    query_analyzer: Annotated[QueryAnalyzer, Depends(get_query_analyzer)],
) -> HybridRetriever:
    node_repo = GraphNodeRepository(session)
    edge_repo = GraphEdgeRepository(session)
    evidence_repo = GraphEvidenceRepository(session)
    graph_service = KnowledgeGraphService(
        node_repo=node_repo,
        edge_repo=edge_repo,
        evidence_repo=evidence_repo,
        audit_service=AuditService(AuditLogRepository(session)),
    )
    return HybridRetriever(
        query_analyzer=query_analyzer,
        bm25=BM25Search(session),
        vector_search=VectorSearch(session),
        graph_expansion=GraphExpansion(graph_service),
        embedding_provider=get_optional_embedding_provider(),
        reranker=get_reranker_service(),
        run_repo=RetrievalRunRepository(session),
        result_repo=RetrievalResultRepository(session),
    )


def get_optional_embedding_provider() -> EmbeddingProvider | None:
    """None (not a raised exception) when unconfigured - HybridRetriever
    degrades to BM25+graph-only in that case, which is a perfectly usable
    retrieval mode. require_embedding_provider below is the loud version,
    for the two routes that genuinely cannot run without one."""
    try:
        return get_embedding_provider()
    except ConfigurationError:
        return None


def require_embedding_provider(
    embedding_provider: Annotated[
        EmbeddingProvider | None, Depends(get_optional_embedding_provider)
    ],
) -> EmbeddingProvider:
    if embedding_provider is None:
        raise ServiceUnavailableError(
            "No embedding provider is configured (EMBEDDING_PROVIDER/API key missing) - "
            "hybrid retrieval (BM25+vector+graph) cannot run. POST /retrieve/graph needs no "
            "embedding provider and remains available."
        )
    return embedding_provider


def get_retrieval_run_repo(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RetrievalRunRepository:
    return RetrievalRunRepository(session)


def get_retrieval_result_repo(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RetrievalResultRepository:
    return RetrievalResultRepository(session)


async def _cite_candidates(
    candidates: list[RetrievalCandidate], citation_engine: CitationEngine
) -> list[RetrievalResultItem]:
    items: list[RetrievalResultItem] = []
    for candidate in candidates:
        citation = await citation_engine.cite(
            EmbeddingSourceType(candidate.source_type), candidate.source_id
        )
        items.append(RetrievalResultItem(candidate=candidate, citation=citation))
    return items


# -- routes -------------------------------------------------------------------


@retrieval_router.post(
    "",
    response_model=ApiResponse[RetrieveResponseData],
    dependencies=[Depends(require_permission("retrieval:read"))],
)
async def retrieve(
    body: RetrieveRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    retriever: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
    citation_engine: Annotated[CitationEngine, Depends(get_citation_engine)],
    _embedding_provider: Annotated[EmbeddingProvider, Depends(require_embedding_provider)],
) -> ApiResponse[RetrieveResponseData]:
    settings = get_settings()
    result = await retriever.retrieve(
        HybridRetrievalRequest(
            query=body.query,
            top_k=body.top_k or settings.retrieval_top_k,
            max_candidates=body.max_candidates or settings.retrieval_max_candidates,
            graph_expansion_depth=(
                body.graph_expansion_depth or settings.retrieval_graph_expansion_depth
            ),
            source_types=tuple(body.source_types) if body.source_types else None,
            requested_by_user_id=current_user.id,
        )
    )
    items = await _cite_candidates(result.candidates, citation_engine)
    return ApiResponse(
        data=RetrieveResponseData(retrieval_run_id=result.run.id, results=items)
    )


@retrieval_router.post(
    "/context",
    response_model=ApiResponse[RetrieveContextResponseData],
    dependencies=[Depends(require_permission("retrieval:read"))],
)
async def retrieve_context(
    body: RetrieveRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    retriever: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
    context_service: Annotated[ContextService, Depends(get_context_service)],
    _embedding_provider: Annotated[EmbeddingProvider, Depends(require_embedding_provider)],
) -> ApiResponse[RetrieveContextResponseData]:
    settings = get_settings()
    result = await retriever.retrieve(
        HybridRetrievalRequest(
            query=body.query,
            top_k=body.top_k or settings.retrieval_top_k,
            max_candidates=body.max_candidates or settings.retrieval_max_candidates,
            graph_expansion_depth=(
                body.graph_expansion_depth or settings.retrieval_graph_expansion_depth
            ),
            source_types=tuple(body.source_types) if body.source_types else None,
            requested_by_user_id=current_user.id,
        )
    )
    context = await context_service.build_context(body.query, result.candidates)
    return ApiResponse(
        data=RetrieveContextResponseData(retrieval_run_id=result.run.id, context=context)
    )


@retrieval_router.post(
    "/graph",
    response_model=ApiResponse[RetrieveResponseData],
    dependencies=[Depends(require_permission("retrieval:read"))],
)
async def retrieve_graph(
    body: RetrieveGraphRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    retriever: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
    citation_engine: Annotated[CitationEngine, Depends(get_citation_engine)],
) -> ApiResponse[RetrieveResponseData]:
    settings = get_settings()
    result = await retriever.retrieve_graph_only(
        query=body.query,
        seed_canonical_ids=body.seed_canonical_ids,
        top_k=body.top_k or settings.retrieval_top_k,
        depth=body.depth or settings.retrieval_graph_expansion_depth,
        requested_by_user_id=current_user.id,
    )
    items = await _cite_candidates(result.candidates, citation_engine)
    return ApiResponse(
        data=RetrieveResponseData(retrieval_run_id=result.run.id, results=items)
    )


@retrieval_runs_router.get(
    "/{retrieval_run_id}",
    response_model=ApiResponse[RetrievalRunDetailRead],
    dependencies=[Depends(require_permission("retrieval:read"))],
)
async def get_retrieval_run(
    retrieval_run_id: uuid.UUID,
    run_repo: Annotated[RetrievalRunRepository, Depends(get_retrieval_run_repo)],
    result_repo: Annotated[RetrievalResultRepository, Depends(get_retrieval_result_repo)],
    citation_engine: Annotated[CitationEngine, Depends(get_citation_engine)],
) -> ApiResponse[RetrievalRunDetailRead]:
    run = await run_repo.get_by_id(retrieval_run_id)
    if run is None:
        raise NotFoundError(f"Retrieval run {retrieval_run_id} not found")

    rows = await result_repo.list_for_run(retrieval_run_id)
    candidates = [
        RetrievalCandidate(
            source_type=row.source_type.value,
            source_id=row.source_id,
            retrieval_method=row.retrieval_method.value,
            score=row.score,
            rerank_score=row.rerank_score,
            final_rank=row.final_rank,
        )
        for row in rows
    ]
    items = await _cite_candidates(candidates, citation_engine)
    return ApiResponse(
        data=RetrievalRunDetailRead(run=RetrievalRunRead.model_validate(run), results=items)
    )
