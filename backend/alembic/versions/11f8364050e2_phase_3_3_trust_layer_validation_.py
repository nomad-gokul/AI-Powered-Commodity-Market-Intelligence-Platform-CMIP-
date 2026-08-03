"""phase 3.3 trust layer: validation confidence normalization review queue

Revision ID: 11f8364050e2
Revises: ec2182df58d8
Create Date: 2026-08-04 00:22:52.663952
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "11f8364050e2"
down_revision: str | None = "ec2182df58d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALIDATION_CATEGORIES = (
    "date",
    "currency",
    "quantity",
    "unit",
    "duplicate",
    "hs_code",
    "incoterm",
    "exchange_rate",
    "geometry",
    "consistency",
    "conflict",
)


def upgrade() -> None:
    op.create_table(
        "trust_pipeline_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("extraction_run_id", sa.UUID(), nullable=False),
        sa.Column("pipeline_version", sa.String(length=32), nullable=False),
        sa.Column("rule_registry_version", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "completed", "failed", name="trust_pipeline_status"
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("entities_validated", sa.Integer(), nullable=False),
        sa.Column("entities_flagged_for_review", sa.Integer(), nullable=False),
        sa.Column("average_confidence", sa.Float(), nullable=True),
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
            name=op.f("fk_trust_pipeline_runs_extraction_run_id_extraction_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trust_pipeline_runs")),
    )
    op.create_table(
        "confidence_scores",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("extraction_score", sa.Float(), nullable=False),
        sa.Column("geometry_score", sa.Float(), nullable=False),
        sa.Column("layout_score", sa.Float(), nullable=False),
        sa.Column("table_score", sa.Float(), nullable=False),
        sa.Column("consistency_score", sa.Float(), nullable=False),
        sa.Column("normalization_score", sa.Float(), nullable=False),
        sa.Column("validation_score", sa.Float(), nullable=False),
        sa.Column("provider_score", sa.Float(), nullable=False),
        sa.Column("explanation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["extracted_entities.id"],
            name=op.f("fk_confidence_scores_entity_id_extracted_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entity_id", name=op.f("pk_confidence_scores")),
    )
    op.create_table(
        "normalization_results",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("canonical_id", sa.String(length=256), nullable=True),
        sa.Column("canonical_name", sa.String(length=256), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("normalization_method", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["extracted_entities.id"],
            name=op.f("fk_normalization_results_entity_id_extracted_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entity_id", name=op.f("pk_normalization_results")),
    )
    op.create_table(
        "review_queue",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("extraction_run_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "priority",
            sa.Enum("low", "medium", "high", "critical", name="review_priority"),
            nullable=False,
        ),
        sa.Column("assigned_to", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "in_review", "resolved", "dismissed", name="review_status"),
            nullable=False,
        ),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name=op.f("fk_review_queue_assigned_to_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["extracted_entities.id"],
            name=op.f("fk_review_queue_entity_id_extracted_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["extraction_runs.id"],
            name=op.f("fk_review_queue_extraction_run_id_extraction_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_queue")),
    )
    op.create_table(
        "validation_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("extraction_run_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("validation_rule", sa.String(length=128), nullable=False),
        sa.Column(
            "validation_type",
            sa.Enum(*_VALIDATION_CATEGORIES, name="validation_category"),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("info", "warning", "error", "critical", name="validation_severity"),
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["extracted_entities.id"],
            name=op.f("fk_validation_results_entity_id_extracted_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["extraction_runs.id"],
            name=op.f("fk_validation_results_extraction_run_id_extraction_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validation_results")),
    )
    op.add_column(
        "extraction_runs", sa.Column("extraction_fingerprint", sa.String(length=64), nullable=True)
    )
    op.create_index(
        op.f("ix_extraction_runs_extraction_fingerprint"),
        "extraction_runs",
        ["extraction_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_extraction_runs_extraction_fingerprint"), table_name="extraction_runs")
    op.drop_column("extraction_runs", "extraction_fingerprint")
    op.drop_table("validation_results")
    op.drop_table("review_queue")
    op.drop_table("normalization_results")
    op.drop_table("confidence_scores")
    op.drop_table("trust_pipeline_runs")

    # drop_table() does not drop the native Postgres ENUM types
    # create_table() implicitly created - see 23293813c565 (Phase 3.2)
    # and 4d65d7e68757 (Phase 2) for the same fix.
    bind = op.get_bind()
    sa.Enum(name="validation_category").drop(bind, checkfirst=True)
    sa.Enum(name="validation_severity").drop(bind, checkfirst=True)
    sa.Enum(name="review_priority").drop(bind, checkfirst=True)
    sa.Enum(name="review_status").drop(bind, checkfirst=True)
    sa.Enum(name="trust_pipeline_status").drop(bind, checkfirst=True)
