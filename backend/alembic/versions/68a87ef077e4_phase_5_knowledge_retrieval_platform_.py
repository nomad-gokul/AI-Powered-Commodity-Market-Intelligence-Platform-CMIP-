"""phase 5 knowledge retrieval platform: pgvector, embeddings, retrieval runs/results

Installs the pgvector extension (checkfirst-safe - CREATE EXTENSION IF NOT
EXISTS), creates the polymorphic embeddings table (a fixed-width 1536-dim
vector column - see app.modules.retrieval.models' module docstring for why
the width is fixed at migration time), the retrieval_runs/retrieval_results
run-tracking pair, and adds a generated tsvector column + GIN index to
document_chunks for BM25 full-text search (Phase 2's table - an additive,
non-breaking touch, the "integration requires it" exception to
Pre-Phase-5's "do not modify previous phases").

HNSW is built by default for the embeddings vector column (better recall,
no training step, pgvector's current recommendation); IVFFlat remains
available as a future migration on the same column if a workload ever
needs it - building both by default is redundant index-maintenance cost.

Revision ID: 68a87ef077e4
Revises: a1494375c932
Create Date: 2026-08-04 02:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "68a87ef077e4"
down_revision: str | None = "a1494375c932"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSION = 1536


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "document_chunk",
                "graph_node",
                "graph_edge",
                "canonical_entity",
                "ontology_definition",
                name="embedding_source_type",
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=256), nullable=False),
        sa.Column("embedding_provider", sa.String(length=32), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_vector", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embeddings")),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "embedding_provider",
            "embedding_model",
            name="uq_embeddings_source_provider_model",
        ),
    )
    op.create_index(
        "ix_embeddings_vector_cosine_hnsw",
        "embeddings",
        ["embedding_vector"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding_vector": "vector_cosine_ops"},
    )

    op.create_table(
        "retrieval_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("reranker", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=False),
        sa.Column("retrieved_results", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", name="retrieval_run_status"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_retrieval_runs_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_runs")),
    )

    op.create_table(
        "retrieval_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("retrieval_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "document_chunk",
                "graph_node",
                "graph_edge",
                "canonical_entity",
                "ontology_definition",
                name="retrieval_result_source_type",
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=256), nullable=False),
        sa.Column(
            "retrieval_method",
            sa.Enum("bm25", "vector", "graph_expansion", "hybrid", name="retrieval_method"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("final_rank", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_run_id"],
            ["retrieval_runs.id"],
            name=op.f("fk_retrieval_results_retrieval_run_id_retrieval_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_results")),
    )

    op.add_column(
        "document_chunks",
        sa.Column(
            "text_search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_chunks_text_search",
        "document_chunks",
        ["text_search"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_text_search", table_name="document_chunks")
    op.drop_column("document_chunks", "text_search")

    op.drop_table("retrieval_results")
    op.drop_table("retrieval_runs")
    op.drop_index("ix_embeddings_vector_cosine_hnsw", table_name="embeddings")
    op.drop_table("embeddings")

    # drop_table() does not drop the native Postgres ENUM types
    # create_table() implicitly created - see 11f8364050e2 (Phase 3.3) for
    # the same fix. The vector extension itself is deliberately NOT
    # dropped: DROP EXTENSION is a much higher-blast-radius operation than
    # this migration's own additions, and leaving it installed is harmless.
    bind = op.get_bind()
    sa.Enum(name="retrieval_method").drop(bind, checkfirst=True)
    sa.Enum(name="retrieval_run_status").drop(bind, checkfirst=True)
    sa.Enum(name="retrieval_result_source_type").drop(bind, checkfirst=True)
    sa.Enum(name="embedding_source_type").drop(bind, checkfirst=True)
