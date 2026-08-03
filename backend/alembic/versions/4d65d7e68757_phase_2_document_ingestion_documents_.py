"""phase 2 document ingestion: documents, versions, processing jobs, chunks

Revision ID: 4d65d7e68757
Revises: 8329376ff7a6
Create Date: 2026-08-03 05:48:47.656983
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4d65d7e68757"
down_revision: str | None = "8329376ff7a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "storage_provider",
            sa.Enum("local", "s3", name="storage_provider_kind"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "upload_status",
            sa.Enum("pending", "uploaded", "failed", name="upload_status"),
            nullable=False,
        ),
        sa.Column(
            "processing_status",
            sa.Enum(
                "uploaded",
                "queued",
                "processing",
                "ocr",
                "extracting",
                "chunking",
                "completed",
                "failed",
                "cancelled",
                name="processing_status",
            ),
            nullable=False,
        ),
        sa.Column("processing_progress", sa.SmallInteger(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_documents_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_sha256_hash"), "documents", ["sha256_hash"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
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
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
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
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_document_versions_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version"),
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.Enum("ingestion", "reprocess", name="job_type"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "retrying",
                "completed",
                "failed",
                "cancelled",
                name="job_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "current_stage",
            sa.Enum(
                "uploaded",
                "queued",
                "processing",
                "ocr",
                "extracting",
                "chunking",
                "completed",
                "failed",
                "cancelled",
                name="processing_status",
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.SmallInteger(), nullable=False),
        sa.Column("retries", sa.SmallInteger(), nullable=False),
        sa.Column("max_retries", sa.SmallInteger(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            name=op.f("fk_processing_jobs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_jobs")),
    )


def downgrade() -> None:
    op.drop_table("processing_jobs")
    op.drop_table("document_versions")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_documents_sha256_hash"), table_name="documents")
    op.drop_table("documents")

    # create_table() auto-creates the native Postgres ENUM types the first
    # time a column uses them, but drop_table() does not drop those types -
    # they're separate DB objects and must be dropped explicitly, or a
    # subsequent upgrade fails with "type already exists".
    bind = op.get_bind()
    sa.Enum(name="processing_status").drop(bind, checkfirst=True)
    sa.Enum(name="job_status").drop(bind, checkfirst=True)
    sa.Enum(name="job_type").drop(bind, checkfirst=True)
    sa.Enum(name="upload_status").drop(bind, checkfirst=True)
    sa.Enum(name="storage_provider_kind").drop(bind, checkfirst=True)
