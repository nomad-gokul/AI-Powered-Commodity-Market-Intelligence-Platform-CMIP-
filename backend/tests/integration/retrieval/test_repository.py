"""Integration tests for Phase 5's data-access layer against a real,
pgvector-enabled Postgres: EmbeddingRepository's lookups, BM25Search's real
full-text search (websearch_to_tsquery/ts_rank_cd against the generated
text_search column), and VectorSearch's real pgvector distance ordering
(cosine/L2/inner-product) - none of these are meaningfully testable
against a mock, the same reasoning graph/test_repository.py gives for its
own recursive-CTE traversal tests.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentChunk, StorageProviderKind
from app.modules.retrieval.bm25 import BM25Search
from app.modules.retrieval.models import Embedding, EmbeddingSourceType
from app.modules.retrieval.repository import EmbeddingRepository
from app.modules.retrieval.vector_search import DistanceMetric, VectorSearch

pytestmark = pytest.mark.asyncio


def _unit_vector(dominant_index: int, dimension: int = 1536) -> list[float]:
    """A basis vector (1.0 at dominant_index, 0.0 elsewhere) - cosine
    distance between two of these is 0.0 (identical direction) or 1.0
    (orthogonal), giving deterministic, easy-to-assert-on distances."""
    vector = [0.0] * dimension
    vector[dominant_index] = 1.0
    return vector


async def _document(session: AsyncSession) -> Document:
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
    return document


async def _chunk(
    session: AsyncSession, document_id: uuid.UUID, *, text: str, chunk_index: int = 0
) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        page_number=1,
        text=text,
        token_count=len(text.split()),
        metadata_json={},
    )
    session.add(chunk)
    await session.flush()
    return chunk


def _embedding(
    *,
    source_id: str,
    vector: list[float],
    source_type: EmbeddingSourceType = EmbeddingSourceType.GRAPH_NODE,
) -> Embedding:
    return Embedding(
        id=uuid.uuid4(),
        source_type=source_type,
        source_id=source_id,
        embedding_provider="test",
        embedding_model="test-model",
        embedding_dimension=1536,
        embedding_hash=uuid.uuid4().hex,
        embedding_vector=vector,
    )


class TestEmbeddingRepository:
    async def test_get_by_source_returns_none_when_absent(self, db_session: AsyncSession) -> None:
        repo = EmbeddingRepository(db_session)
        result = await repo.get_by_source(
            source_type="graph_node",
            source_id="missing",
            embedding_provider="test",
            embedding_model="m",
        )
        assert result is None

    async def test_create_then_get_by_source_round_trips(self, db_session: AsyncSession) -> None:
        repo = EmbeddingRepository(db_session)
        source_id = f"company:{uuid.uuid4().hex[:8]}"
        created = await repo.create(_embedding(source_id=source_id, vector=_unit_vector(0)))

        found = await repo.get_by_source(
            source_type="graph_node",
            source_id=source_id,
            embedding_provider="test",
            embedding_model="test-model",
        )
        assert found is not None
        assert found.id == created.id

    async def test_list_by_sources_returns_only_matching_provider(
        self, db_session: AsyncSession
    ) -> None:
        repo = EmbeddingRepository(db_session)
        source_id = f"company:{uuid.uuid4().hex[:8]}"
        await repo.create(_embedding(source_id=source_id, vector=_unit_vector(1)))

        matches = await repo.list_by_sources(
            source_type="graph_node", source_ids=[source_id], embedding_provider="test"
        )
        assert source_id in matches

        no_matches = await repo.list_by_sources(
            source_type="graph_node",
            source_ids=[source_id],
            embedding_provider="a-different-provider",
        )
        assert no_matches == {}


class TestBM25Search:
    async def test_finds_chunk_by_real_full_text_search(self, db_session: AsyncSession) -> None:
        document = await _document(db_session)
        await _chunk(
            db_session,
            document.id,
            text="Adani Ports SEZ owns and operates Mundra Port terminal.",
            chunk_index=0,
        )
        await _chunk(
            db_session,
            document.id,
            text="Crude oil prices rose sharply in the third quarter.",
            chunk_index=1,
        )

        hits = await BM25Search(db_session).search("Mundra Port")

        assert len(hits) == 1
        assert hits[0].score > 0

    async def test_no_match_returns_empty_list(self, db_session: AsyncSession) -> None:
        document = await _document(db_session)
        await _chunk(db_session, document.id, text="Crude oil prices rose sharply.")

        hits = await BM25Search(db_session).search("zebra unicorn nonsense")

        assert hits == []

    async def test_blank_query_returns_empty_list_without_querying(
        self, db_session: AsyncSession
    ) -> None:
        assert await BM25Search(db_session).search("   ") == []

    async def test_respects_limit(self, db_session: AsyncSession) -> None:
        document = await _document(db_session)
        for index in range(3):
            await _chunk(
                db_session,
                document.id,
                text="Mundra Port shipment volumes increased.",
                chunk_index=index,
            )

        hits = await BM25Search(db_session).search("Mundra Port", limit=2)
        assert len(hits) == 2


class TestVectorSearch:
    async def test_cosine_orders_by_similarity(self, db_session: AsyncSession) -> None:
        repo = EmbeddingRepository(db_session)
        identical_id = f"port:{uuid.uuid4().hex[:8]}"
        orthogonal_id = f"port:{uuid.uuid4().hex[:8]}"
        await repo.create(_embedding(source_id=identical_id, vector=_unit_vector(0)))
        await repo.create(_embedding(source_id=orthogonal_id, vector=_unit_vector(1)))

        hits = await VectorSearch(db_session).search(_unit_vector(0), metric=DistanceMetric.COSINE)

        hit_by_id = {hit.source_id: hit for hit in hits}
        assert hit_by_id[identical_id].distance == pytest.approx(0.0, abs=1e-6)
        assert hit_by_id[identical_id].similarity == pytest.approx(1.0, abs=1e-6)
        assert hit_by_id[orthogonal_id].distance == pytest.approx(1.0, abs=1e-6)
        # Identical direction must rank before the orthogonal vector.
        assert hits.index(hit_by_id[identical_id]) < hits.index(hit_by_id[orthogonal_id])

    async def test_filters_by_source_type(self, db_session: AsyncSession) -> None:
        repo = EmbeddingRepository(db_session)
        node_id = f"port:{uuid.uuid4().hex[:8]}"
        edge_id = str(uuid.uuid4())
        await repo.create(
            _embedding(
                source_id=node_id,
                vector=_unit_vector(2),
                source_type=EmbeddingSourceType.GRAPH_NODE,
            )
        )
        await repo.create(
            _embedding(
                source_id=edge_id,
                vector=_unit_vector(2),
                source_type=EmbeddingSourceType.GRAPH_EDGE,
            )
        )

        hits = await VectorSearch(db_session).search(_unit_vector(2), source_type="graph_node")

        assert {hit.source_id for hit in hits} == {node_id}

    async def test_l2_and_inner_product_metrics_execute_without_error(
        self, db_session: AsyncSession
    ) -> None:
        repo = EmbeddingRepository(db_session)
        await repo.create(_embedding(source_id=f"c:{uuid.uuid4().hex[:8]}", vector=_unit_vector(3)))

        l2_hits = await VectorSearch(db_session).search(_unit_vector(3), metric=DistanceMetric.L2)
        inner_product_hits = await VectorSearch(db_session).search(
            _unit_vector(3), metric=DistanceMetric.INNER_PRODUCT
        )
        assert l2_hits
        assert inner_product_hits
