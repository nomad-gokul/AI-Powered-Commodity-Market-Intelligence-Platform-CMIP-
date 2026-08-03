"""phase 3.2 semantic extraction: extraction_runs, entities, mentions, tables, cells

Revision ID: 23293813c565
Revises: 5cf29ad980c9
Create Date: 2026-08-03 13:14:15.802005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "23293813c565"
down_revision: str | None = "5cf29ad980c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_TYPES = (
    "commodity",
    "port",
    "company",
    "country",
    "currency",
    "price",
    "contract",
    "date",
    "quantity",
    "unit",
    "incoterm",
    "hs_code",
    "organization",
    "terminal",
    "vessel",
)


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("pipeline_version", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", name="extraction_status"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_extraction_runs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_runs")),
    )
    op.create_table(
        "extracted_entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("extraction_run_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.Enum(*_ENTITY_TYPES, name="entity_type"), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bounding_box", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_chunk", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
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
            ["extraction_run_id"],
            ["extraction_runs.id"],
            name=op.f("fk_extracted_entities_extraction_run_id_extraction_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk"],
            ["document_chunks.id"],
            name=op.f("fk_extracted_entities_source_chunk_document_chunks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extracted_entities")),
    )
    op.create_table(
        "extracted_tables",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("extraction_run_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            ["extraction_run_id"],
            ["extraction_runs.id"],
            name=op.f("fk_extracted_tables_extraction_run_id_extraction_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extracted_tables")),
    )
    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("character_offset", sa.Integer(), nullable=True),
        sa.Column("surrounding_text", sa.Text(), nullable=False),
        sa.Column("source_chunk", sa.UUID(), nullable=True),
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
            ["entity_id"],
            ["extracted_entities.id"],
            name=op.f("fk_entity_mentions_entity_id_extracted_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk"],
            ["document_chunks.id"],
            name=op.f("fk_entity_mentions_source_chunk_document_chunks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_mentions")),
    )
    op.create_table(
        "table_cells",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("table_id", sa.UUID(), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False),
        sa.Column("column", sa.Integer(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
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
            ["table_id"],
            ["extracted_tables.id"],
            name=op.f("fk_table_cells_table_id_extracted_tables"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_table_cells")),
    )


def downgrade() -> None:
    op.drop_table("table_cells")
    op.drop_table("entity_mentions")
    op.drop_table("extracted_tables")
    op.drop_table("extracted_entities")
    op.drop_table("extraction_runs")

    # drop_table() does not drop the native Postgres ENUM types
    # create_table() implicitly created - see the Phase 2 migration
    # (4d65d7e68757) for the same fix and the round-trip failure it
    # was written to resolve.
    bind = op.get_bind()
    sa.Enum(name="entity_type").drop(bind, checkfirst=True)
    sa.Enum(name="extraction_status").drop(bind, checkfirst=True)
