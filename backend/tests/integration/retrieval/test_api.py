"""End-to-end retrieval API tests against the real app, database, and
Redis. No embedding provider is configured in this environment (no real
OPENAI_API_KEY/GROQ_API_KEY - see docs/ARCHITECTURE.md), which is itself
exercised as a real scenario: POST /retrieve and /retrieve/context must
degrade to a clean 503 (see api.py's require_embedding_provider), while
POST /retrieve/graph (which never needs an embedding provider) and
GET /retrieval-runs/{id} are exercised fully, end to end, for real.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.models import GraphEdge, GraphNode, GraphNodeStatus
from tests.integration.extraction.test_api import (
    _register_and_login,
)


async def _seed_company_owns_port(session: AsyncSession) -> tuple[GraphNode, GraphNode, GraphEdge]:
    company = GraphNode(
        canonical_id=f"company:adani_ports_{uuid.uuid4().hex[:8]}",
        node_type="company",
        display_name="Adani Ports SEZ",
        aliases_json=["Adani Ports SEZ"],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
    )
    port = GraphNode(
        canonical_id=f"port:mundra_{uuid.uuid4().hex[:8]}",
        node_type="port",
        display_name="Mundra Port",
        aliases_json=["Mundra Port"],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
    )
    session.add_all([company, port])
    await session.flush()

    edge = GraphEdge(
        source_node_id=company.id,
        target_node_id=port.id,
        relationship_type="owns",
        confidence=0.8,
        evidence_count=1,
        provenance_json={},
    )
    session.add(edge)
    await session.flush()
    return company, port, edge


class TestRetrieveRequiresAuthAndPermission:
    async def test_retrieve_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/retrieve", json={"query": "test"})
        assert response.status_code == 401

    async def test_retrieve_context_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/retrieve/context", json={"query": "test"})
        assert response.status_code == 401

    async def test_retrieve_graph_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/retrieve/graph", json={"query": "test"})
        assert response.status_code == 401

    async def test_get_retrieval_run_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/retrieval-runs/{uuid.uuid4()}")
        assert response.status_code == 401

    async def test_freshly_registered_viewer_has_retrieval_read_by_default(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Registration defaults to the viewer role, which Phase 5's own
        grant migration gives retrieval:read - confirming that migration
        actually took effect, not just that it exists."""
        token = await _register_and_login(client)
        response = await client.post(
            "/api/v1/retrieve/graph",
            json={"query": "", "seed_canonical_ids": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200


class TestRetrieveWithoutEmbeddingProvider:
    """This dev/test environment has no configured embedding provider -
    the real, honest state to test against, not a mocked-away one."""

    async def test_retrieve_returns_503(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        response = await client.post(
            "/api/v1/retrieve",
            json={"query": "who owns Mundra Port?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "service_unavailable"

    async def test_retrieve_context_returns_503(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        response = await client.post(
            "/api/v1/retrieve/context",
            json={"query": "who owns Mundra Port?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 503


class TestRetrieveGraph:
    async def test_returns_expanded_nodes_and_edges_from_explicit_seeds(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        company, port, edge = await _seed_company_owns_port(db_session)
        token = await _register_and_login(client)

        response = await client.post(
            "/api/v1/retrieve/graph",
            json={"query": "", "seed_canonical_ids": [company.canonical_id]},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        body = response.json()["data"]
        source_ids = {r["candidate"]["source_id"] for r in body["results"]}
        assert str(port.id) in source_ids
        assert str(edge.id) in source_ids
        for result in body["results"]:
            assert "citation" in result
            assert result["citation"]["source_id"]

    async def test_auto_detects_seed_entities_from_query_text(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        company, port, _edge = await _seed_company_owns_port(db_session)
        token = await _register_and_login(client)

        response = await client.post(
            "/api/v1/retrieve/graph",
            json={"query": f"What does {company.display_name} own?"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        source_ids = {
            r["candidate"]["source_id"] for r in response.json()["data"]["results"]
        }
        assert str(port.id) in source_ids

    async def test_unknown_seed_returns_empty_results_not_an_error(
        self, client: AsyncClient
    ) -> None:
        token = await _register_and_login(client)
        response = await client.post(
            "/api/v1/retrieve/graph",
            json={"query": "", "seed_canonical_ids": ["company:does_not_exist"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["results"] == []


class TestGetRetrievalRun:
    async def test_returns_the_persisted_run_and_its_results(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        company, port, _edge = await _seed_company_owns_port(db_session)
        token = await _register_and_login(client)

        retrieve_response = await client.post(
            "/api/v1/retrieve/graph",
            json={"query": "", "seed_canonical_ids": [company.canonical_id]},
            headers={"Authorization": f"Bearer {token}"},
        )
        run_id = retrieve_response.json()["data"]["retrieval_run_id"]

        response = await client.get(
            f"/api/v1/retrieval-runs/{run_id}", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["run"]["id"] == run_id
        assert body["run"]["status"] == "completed"
        source_ids = {r["candidate"]["source_id"] for r in body["results"]}
        assert str(port.id) in source_ids

    async def test_unknown_run_id_returns_404(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/retrieval-runs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 404
