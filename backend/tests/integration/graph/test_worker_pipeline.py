"""End-to-end test of the graph build pipeline (app/worker/tasks.py's
run_graph_rebuild), called directly against real Postgres - real
RelationshipRuleRegistry, real repositories, real recursive-CTE
traversal, no LLM involved anywhere.

run_graph_rebuild uses AsyncSessionLocal directly (a real worker process
has no HTTP request to hang a session override off), so it does NOT
participate in db_session's transaction-rollback isolation - rows
created here are cleaned up explicitly, same pattern
tests/integration/extraction/trust/test_worker_pipeline.py established.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.modules.documents.models import Document, DocumentChunk, StorageProviderKind
from app.modules.extraction.models import (
    EntityMention,
    EntityType,
    ExtractedEntity,
    ExtractionRun,
    ExtractionStatus,
)
from app.modules.extraction.trust.models import (
    ConfidenceScore,
    NormalizationResult,
    TrustPipelineRun,
)
from app.modules.graph.models import GraphBuildRun, GraphEdge, GraphEvidence, GraphNode
from app.worker.tasks import run_graph_rebuild

pytestmark = pytest.mark.asyncio


class _FakeRedisPool:
    """Stands in for the real ArqRedis pool a live arq Worker always
    injects into ctx["redis"] (see arq.worker.Worker.__init__) - these
    tests call run_graph_rebuild directly, never through a real Worker.
    Phase 5's embedding-generation hook (run_graph_rebuild's tail, reached
    only on a successful completion) needs it to exist; this file's tests
    don't care whether that follow-up job was actually enqueued, so a
    no-op is sufficient."""

    async def enqueue_job(self, *args: object, **kwargs: object) -> None:
        return None


_CTX: dict[str, object] = {"redis": _FakeRedisPool()}


class _Fixture:
    def __init__(
        self,
        *,
        document_id: uuid.UUID,
        extraction_run_id: uuid.UUID,
        graph_build_run_id: uuid.UUID,
        company_entity_id: uuid.UUID,
        port_entity_id: uuid.UUID,
        chunk_id: uuid.UUID,
    ) -> None:
        self.document_id = document_id
        self.extraction_run_id = extraction_run_id
        self.graph_build_run_id = graph_build_run_id
        self.company_entity_id = company_entity_id
        self.port_entity_id = port_entity_id
        self.chunk_id = chunk_id


@asynccontextmanager
async def _create_trusted_extraction_with_relationship() -> AsyncIterator[_Fixture]:
    chunk_text = "Adani Ports owns Mundra Port in Gujarat."
    async with AsyncSessionLocal() as session:
        document = Document(
            filename=f"{uuid.uuid4().hex}.pdf",
            original_filename="report.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            file_size=100,
            sha256_hash=uuid.uuid4().hex + "0" * 32,
            storage_provider=StorageProviderKind.LOCAL,
            storage_key=f"{uuid.uuid4().hex}.pdf",
        )
        session.add(document)
        await session.flush()

        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            page_number=1,
            text=chunk_text,
            token_count=12,
            metadata_json={},
        )
        session.add(chunk)
        await session.flush()

        run = ExtractionRun(
            document_id=document.id,
            pipeline_version="3.2.0",
            provider="groq",
            model="test-model",
            prompt_version="1.0",
            prompt_hash="hash",
            status=ExtractionStatus.COMPLETED,
            token_usage={},
        )
        session.add(run)
        await session.flush()

        company = ExtractedEntity(
            extraction_run_id=run.id,
            entity_type=EntityType.COMPANY,
            raw_value="Adani Ports",
            confidence=0.9,
            page_number=1,
            source_chunk=chunk.id,
            provider="groq",
            model="test-model",
            prompt_version="1.0",
        )
        port = ExtractedEntity(
            extraction_run_id=run.id,
            entity_type=EntityType.PORT,
            raw_value="Mundra Port",
            confidence=0.9,
            page_number=1,
            source_chunk=chunk.id,
            provider="groq",
            model="test-model",
            prompt_version="1.0",
        )
        session.add_all([company, port])
        await session.flush()

        session.add_all(
            [
                EntityMention(
                    entity_id=company.id,
                    page_number=1,
                    character_offset=chunk_text.index("Adani Ports"),
                    surrounding_text=chunk_text,
                    source_chunk=chunk.id,
                ),
                EntityMention(
                    entity_id=port.id,
                    page_number=1,
                    character_offset=chunk_text.index("Mundra Port"),
                    surrounding_text=chunk_text,
                    source_chunk=chunk.id,
                ),
            ]
        )
        session.add_all(
            [
                NormalizationResult(
                    entity_id=company.id,
                    canonical_id="company:adani_ports",
                    canonical_name="Adani Ports",
                    normalized_value="Adani Ports",
                    normalization_method="slug_derivation",
                    confidence=1.0,
                ),
                NormalizationResult(
                    entity_id=port.id,
                    canonical_id="port:mundra_port",
                    canonical_name="Mundra Port",
                    normalized_value="Mundra Port",
                    normalization_method="alias_lookup",
                    confidence=1.0,
                ),
            ]
        )
        session.add_all(
            [
                ConfidenceScore(
                    entity_id=company.id,
                    overall_score=0.9,
                    extraction_score=1.0,
                    geometry_score=1.0,
                    layout_score=1.0,
                    table_score=1.0,
                    consistency_score=1.0,
                    normalization_score=1.0,
                    validation_score=1.0,
                    provider_score=1.0,
                    explanation_json={},
                ),
                ConfidenceScore(
                    entity_id=port.id,
                    overall_score=0.9,
                    extraction_score=1.0,
                    geometry_score=1.0,
                    layout_score=1.0,
                    table_score=1.0,
                    consistency_score=1.0,
                    normalization_score=1.0,
                    validation_score=1.0,
                    provider_score=1.0,
                    explanation_json={},
                ),
            ]
        )

        trust_run = TrustPipelineRun(
            extraction_run_id=run.id,
            pipeline_version="3.3.0",
            rule_registry_version="1.0",
            status=ExtractionStatus.COMPLETED,
            entities_validated=2,
            entities_flagged_for_review=0,
            average_confidence=0.9,
        )
        session.add(trust_run)
        await session.flush()

        build_run = GraphBuildRun(extraction_run_id=run.id, status=ExtractionStatus.PENDING)
        session.add(build_run)
        await session.commit()

        fixture = _Fixture(
            document_id=document.id,
            extraction_run_id=run.id,
            graph_build_run_id=build_run.id,
            company_entity_id=company.id,
            port_entity_id=port.id,
            chunk_id=chunk.id,
        )

    try:
        yield fixture
    finally:
        async with AsyncSessionLocal() as session:
            node_ids = (
                await session.execute(
                    select(GraphNode.id).where(
                        GraphNode.canonical_id.in_(["company:adani_ports", "port:mundra_port"])
                    )
                )
            ).scalars().all()
            edge_ids = (
                await session.execute(
                    select(GraphEdge.id).where(
                        (GraphEdge.source_node_id.in_(node_ids))
                        | (GraphEdge.target_node_id.in_(node_ids))
                    )
                )
            ).scalars().all()
            await session.execute(delete(GraphEvidence).where(GraphEvidence.edge_id.in_(edge_ids)))
            await session.execute(delete(GraphEdge).where(GraphEdge.id.in_(edge_ids)))
            await session.execute(delete(GraphNode).where(GraphNode.id.in_(node_ids)))
            await session.execute(
                delete(GraphBuildRun).where(GraphBuildRun.id == fixture.graph_build_run_id)
            )
            await session.execute(
                delete(TrustPipelineRun).where(
                    TrustPipelineRun.extraction_run_id == fixture.extraction_run_id
                )
            )
            entity_ids = [fixture.company_entity_id, fixture.port_entity_id]
            await session.execute(
                delete(ConfidenceScore).where(ConfidenceScore.entity_id.in_(entity_ids))
            )
            await session.execute(
                delete(NormalizationResult).where(NormalizationResult.entity_id.in_(entity_ids))
            )
            await session.execute(
                delete(EntityMention).where(EntityMention.entity_id.in_(entity_ids))
            )
            await session.execute(
                delete(ExtractedEntity).where(
                    ExtractedEntity.extraction_run_id == fixture.extraction_run_id
                )
            )
            await session.execute(
                delete(ExtractionRun).where(ExtractionRun.id == fixture.extraction_run_id)
            )
            await session.execute(delete(DocumentChunk).where(DocumentChunk.id == fixture.chunk_id))
            await session.execute(delete(Document).where(Document.id == fixture.document_id))
            await session.commit()


class TestRunGraphRebuild:
    async def test_full_pipeline_creates_nodes_edge_and_evidence(self) -> None:
        async with _create_trusted_extraction_with_relationship() as fixture:
            await run_graph_rebuild(_CTX, str(fixture.graph_build_run_id))

            async with AsyncSessionLocal() as session:
                build_run = await session.get(GraphBuildRun, fixture.graph_build_run_id)
                assert build_run is not None
                assert build_run.status == ExtractionStatus.COMPLETED
                assert build_run.nodes_created == 2
                assert build_run.edges_created == 1

                company_node = (
                    await session.execute(
                        select(GraphNode).where(GraphNode.canonical_id == "company:adani_ports")
                    )
                ).scalar_one()
                port_node = (
                    await session.execute(
                        select(GraphNode).where(GraphNode.canonical_id == "port:mundra_port")
                    )
                ).scalar_one()
                assert "Adani Ports" in company_node.aliases_json

                edge = (
                    await session.execute(
                        select(GraphEdge).where(
                            GraphEdge.source_node_id == company_node.id,
                            GraphEdge.target_node_id == port_node.id,
                        )
                    )
                ).scalar_one()
                assert edge.relationship_type == "owns"
                assert edge.evidence_count == 1
                assert 0.0 < edge.confidence <= 1.0

                evidence_rows = (
                    await session.execute(
                        select(GraphEvidence).where(GraphEvidence.edge_id == edge.id)
                    )
                ).scalars().all()
                assert len(evidence_rows) == 2
                assert {r.entity_id for r in evidence_rows} == {
                    fixture.company_entity_id,
                    fixture.port_entity_id,
                }

    async def test_rerunning_is_idempotent_not_additive(self) -> None:
        async with _create_trusted_extraction_with_relationship() as fixture:
            await run_graph_rebuild(_CTX, str(fixture.graph_build_run_id))

            async with AsyncSessionLocal() as session:
                build_run = await session.get(GraphBuildRun, fixture.graph_build_run_id)
                assert build_run is not None
                build_run.status = ExtractionStatus.PENDING
                await session.commit()

            await run_graph_rebuild(_CTX, str(fixture.graph_build_run_id))

            async with AsyncSessionLocal() as session:
                company_node = (
                    await session.execute(
                        select(GraphNode).where(GraphNode.canonical_id == "company:adani_ports")
                    )
                ).scalar_one()
                port_node = (
                    await session.execute(
                        select(GraphNode).where(GraphNode.canonical_id == "port:mundra_port")
                    )
                ).scalar_one()
                edges = (
                    await session.execute(
                        select(GraphEdge).where(
                            GraphEdge.source_node_id == company_node.id,
                            GraphEdge.target_node_id == port_node.id,
                        )
                    )
                ).scalars().all()
                assert len(edges) == 1
                assert edges[0].evidence_count == 1

                evidence_rows = (
                    await session.execute(
                        select(GraphEvidence).where(GraphEvidence.edge_id == edges[0].id)
                    )
                ).scalars().all()
                assert len(evidence_rows) == 2

    async def test_missing_build_run_is_a_no_op(self) -> None:
        await run_graph_rebuild({}, str(uuid.uuid4()))

    async def test_extraction_run_without_completed_trust_run_fails_the_build(self) -> None:
        async with AsyncSessionLocal() as session:
            document = Document(
                filename=f"{uuid.uuid4().hex}.pdf",
                original_filename="report.pdf",
                extension=".pdf",
                mime_type="application/pdf",
                file_size=100,
                sha256_hash=uuid.uuid4().hex + "0" * 32,
                storage_provider=StorageProviderKind.LOCAL,
                storage_key=f"{uuid.uuid4().hex}.pdf",
            )
            session.add(document)
            await session.flush()
            run = ExtractionRun(
                document_id=document.id,
                pipeline_version="3.2.0",
                provider="groq",
                model="test-model",
                prompt_version="1.0",
                prompt_hash="hash",
                status=ExtractionStatus.COMPLETED,
                token_usage={},
            )
            session.add(run)
            await session.flush()
            build_run = GraphBuildRun(extraction_run_id=run.id, status=ExtractionStatus.PENDING)
            session.add(build_run)
            await session.commit()
            build_run_id, run_id, document_id = build_run.id, run.id, document.id

        try:
            await run_graph_rebuild({}, str(build_run_id))

            async with AsyncSessionLocal() as session:
                build_run = await session.get(GraphBuildRun, build_run_id)
                assert build_run is not None
                assert build_run.status == ExtractionStatus.FAILED
                assert build_run.error_message is not None
        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(delete(GraphBuildRun).where(GraphBuildRun.id == build_run_id))
                await session.execute(delete(ExtractionRun).where(ExtractionRun.id == run_id))
                await session.execute(delete(Document).where(Document.id == document_id))
                await session.commit()
