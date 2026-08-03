"""End-to-end knowledge-graph API tests against the real app, database,
and Redis. No real worker runs here - trigger_rebuild enqueues a real
ARQ job that nothing consumes in-process, same pattern trust/test_api.py
uses for trigger_validation; these cover the API/RBAC surface, not the
build pipeline itself (see test_worker_pipeline.py for that).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.graph.models import GraphEdge, GraphEvidence, GraphNode, GraphNodeStatus
from tests.integration.extraction.test_api import (
    REGISTER_PAYLOAD,
    _create_document_with_chunk,
    _login,
    _promote,
    _register_and_login,
)


async def _seed_company_owns_port(
    session: AsyncSession, document_id: uuid.UUID, extraction_run_id: uuid.UUID, chunk_id: uuid.UUID
) -> tuple[GraphNode, GraphNode, GraphEdge]:
    company_entity = ExtractedEntity(
        extraction_run_id=extraction_run_id,
        entity_type=EntityType.COMPANY,
        raw_value="Adani Ports",
        confidence=0.9,
        provider="groq",
        model="test-model",
        prompt_version="1.0",
    )
    port_entity = ExtractedEntity(
        extraction_run_id=extraction_run_id,
        entity_type=EntityType.PORT,
        raw_value="Mundra Port",
        confidence=0.9,
        provider="groq",
        model="test-model",
        prompt_version="1.0",
    )
    session.add_all([company_entity, port_entity])
    await session.flush()

    company_node = GraphNode(
        canonical_id=f"company:adani_ports_{uuid.uuid4().hex[:8]}",
        node_type="company",
        display_name="Adani Ports",
        aliases_json=["Adani Ports"],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
    )
    port_node = GraphNode(
        canonical_id=f"port:mundra_{uuid.uuid4().hex[:8]}",
        node_type="port",
        display_name="Mundra Port",
        aliases_json=["Mundra Port"],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
    )
    session.add_all([company_node, port_node])
    await session.flush()

    edge = GraphEdge(
        source_node_id=company_node.id,
        target_node_id=port_node.id,
        relationship_type="owns",
        confidence=0.75,
        evidence_count=1,
        provenance_json={},
    )
    session.add(edge)
    await session.flush()

    session.add_all(
        [
            GraphEvidence(
                edge_id=edge.id,
                document_id=document_id,
                extraction_run_id=extraction_run_id,
                entity_id=company_entity.id,
                page_number=1,
                chunk_id=chunk_id,
                prompt_hash="a" * 64,
            ),
            GraphEvidence(
                edge_id=edge.id,
                document_id=document_id,
                extraction_run_id=extraction_run_id,
                entity_id=port_entity.id,
                page_number=1,
                chunk_id=chunk_id,
                prompt_hash="a" * 64,
            ),
        ]
    )
    await session.flush()
    return company_node, port_node, edge


async def _document_run_chunk(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.modules.documents.repository import DocumentChunkRepository

    document = await _create_document_with_chunk(session)
    chunk = (await DocumentChunkRepository(session).list_for_document(document.id))[0]

    from app.modules.extraction.models import ExtractionRun, ExtractionStatus

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
    return document.id, run.id, chunk.id


class TestTriggerRebuild:
    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/graph/rebuild", json={})
        assert response.status_code == 401

    async def test_viewer_lacks_permission(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.post(
            "/api/v1/graph/rebuild", json={}, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    async def test_analyst_triggers_full_corpus_rebuild(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)

        response = await client.post(
            "/api/v1/graph/rebuild", json={}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 202
        body = response.json()["data"]
        assert body["extraction_run_id"] is None
        assert body["status"] == "pending"

    async def test_scoped_rebuild_missing_extraction_run_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)

        response = await client.post(
            "/api/v1/graph/rebuild",
            json={"extraction_run_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404


class TestBuildRuns:
    async def test_viewer_can_list_and_get_build_runs(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        trigger = await client.post(
            "/api/v1/graph/rebuild", json={}, headers={"Authorization": f"Bearer {token}"}
        )
        build_run_id = trigger.json()["data"]["id"]

        list_response = await client.get(
            "/api/v1/graph/build-runs", headers={"Authorization": f"Bearer {token}"}
        )
        assert list_response.status_code == 200
        assert any(r["id"] == build_run_id for r in list_response.json()["data"])

        get_response = await client.get(
            f"/api/v1/graph/build-runs/{build_run_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_response.status_code == 200
        assert get_response.json()["data"]["id"] == build_run_id

    async def test_missing_build_run_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/graph/build-runs/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestNodesAndEdges:
    async def test_list_and_get_node(self, client: AsyncClient, db_session: AsyncSession) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        company_node, _port_node, _edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )

        list_response = await client.get(
            "/api/v1/graph/nodes",
            params={"node_type": "company"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_response.status_code == 200
        assert any(n["id"] == str(company_node.id) for n in list_response.json()["data"])

        get_response = await client.get(
            f"/api/v1/graph/nodes/{company_node.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert get_response.status_code == 200
        assert get_response.json()["data"]["canonical_id"] == company_node.canonical_id

    async def test_get_missing_node_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/graph/nodes/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 404

    async def test_get_entity_by_canonical_id(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        company_node, _port_node, _edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )

        response = await client.get(
            f"/api/v1/graph/entity/{company_node.canonical_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(company_node.id)

    async def test_get_relationships_for_canonical_id(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        company_node, port_node, edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )

        response = await client.get(
            f"/api/v1/graph/relationships/{company_node.canonical_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        edges = response.json()["data"]
        assert any(e["id"] == str(edge.id) for e in edges)
        assert edges[0]["target_node_id"] == str(port_node.id)

    async def test_list_and_get_edge_and_evidence(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        _company_node, _port_node, edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )

        list_response = await client.get(
            "/api/v1/graph/edges",
            params={"relationship_type": "owns"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_response.status_code == 200
        assert any(e["id"] == str(edge.id) for e in list_response.json()["data"])

        get_response = await client.get(
            f"/api/v1/graph/edges/{edge.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert get_response.status_code == 200

        evidence_response = await client.get(
            f"/api/v1/graph/edges/{edge.id}/evidence", headers={"Authorization": f"Bearer {token}"}
        )
        assert evidence_response.status_code == 200
        assert len(evidence_response.json()["data"]) == 2

    async def test_evidence_for_missing_edge_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/graph/edges/{uuid.uuid4()}/evidence",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestTraversal:
    async def test_neighbors(self, client: AsyncClient, db_session: AsyncSession) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        company_node, port_node, edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )

        response = await client.get(
            f"/api/v1/graph/nodes/{company_node.id}/neighbors",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert any(e["id"] == str(edge.id) for e in response.json()["data"])

    async def test_subgraph(self, client: AsyncClient, db_session: AsyncSession) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        company_node, port_node, edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )

        response = await client.get(
            f"/api/v1/graph/nodes/{company_node.id}/subgraph",
            params={"depth": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()["data"]
        node_ids = {n["id"] for n in body["nodes"]}
        assert {str(company_node.id), str(port_node.id)} <= node_ids
        assert any(e["id"] == str(edge.id) for e in body["edges"])

    async def test_shortest_path(self, client: AsyncClient, db_session: AsyncSession) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        company_node, port_node, edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )

        response = await client.get(
            "/api/v1/graph/path",
            params={
                "source_canonical_id": company_node.canonical_id,
                "target_canonical_id": port_node.canonical_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()["data"]
        assert [n["id"] for n in body["nodes"]] == [str(company_node.id), str(port_node.id)]
        assert body["edges"][0]["id"] == str(edge.id)

    async def test_shortest_path_unreachable_returns_null_data(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document_id, run_id, chunk_id = await _document_run_chunk(db_session)
        company_node, _port_node, _edge = await _seed_company_owns_port(
            db_session, document_id, run_id, chunk_id
        )
        isolated_node = GraphNode(
            canonical_id=f"country:isolated_{uuid.uuid4().hex[:8]}",
            node_type="country",
            display_name="Nowhere",
            aliases_json=[],
            metadata_json={},
            status=GraphNodeStatus.ACTIVE,
        )
        db_session.add(isolated_node)
        await db_session.flush()

        response = await client.get(
            "/api/v1/graph/path",
            params={
                "source_canonical_id": company_node.canonical_id,
                "target_canonical_id": isolated_node.canonical_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"] is None


class TestMerge:
    async def test_requires_analyst_permission(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.post(
            "/api/v1/graph/merge",
            json={"source_node_id": str(uuid.uuid4()), "target_node_id": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_analyst_merges_duplicate_nodes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)

        survivor = GraphNode(
            canonical_id=f"company:x_{uuid.uuid4().hex[:8]}",
            node_type="company",
            display_name="X",
            aliases_json=["X"],
            metadata_json={},
            status=GraphNodeStatus.ACTIVE,
        )
        duplicate = GraphNode(
            canonical_id=f"company:x_ltd_{uuid.uuid4().hex[:8]}",
            node_type="company",
            display_name="X Ltd",
            aliases_json=["X Ltd"],
            metadata_json={},
            status=GraphNodeStatus.ACTIVE,
        )
        db_session.add_all([survivor, duplicate])
        await db_session.flush()

        response = await client.post(
            "/api/v1/graph/merge",
            json={"source_node_id": str(duplicate.id), "target_node_id": str(survivor.id)},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["id"] == str(survivor.id)
        assert set(body["aliases_json"]) >= {"X", "X Ltd"}

        await db_session.refresh(duplicate)
        assert duplicate.status == GraphNodeStatus.MERGED
        assert duplicate.merged_into_id == survivor.id
