"""phase 4 knowledge graph: nodes edges evidence ontology relationship types

Seeds ontology_types/relationship_types reference data in this same
migration (unlike Phase 3.3's canonical registry, which is static JSON,
the spec asks for these as real DB tables - see docs/ARCHITECTURE.md's
Phase 4 section). Self-referential FKs (ontology_types.parent_type,
relationship_types.inverse_relationship) are seeded in two passes: first
every row with the self-referential column NULL, then an UPDATE pass -
a single multi-row INSERT can't satisfy a same-table FK for a row
inserted before the row it references.

Revision ID: 59226041fb77
Revises: 11f8364050e2
Create Date: 2026-08-04 01:42:53.014557
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "59226041fb77"
down_revision: str | None = "11f8364050e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ontology_types = sa.table(
    "ontology_types",
    sa.column("id", sa.UUID()),
    sa.column("entity_type", sa.String()),
    sa.column("description", sa.Text()),
    sa.column("parent_type", sa.String()),
    sa.column("metadata_json", postgresql.JSONB()),
)

_relationship_types = sa.table(
    "relationship_types",
    sa.column("id", sa.UUID()),
    sa.column("relationship_name", sa.String()),
    sa.column("inverse_relationship", sa.String()),
    sa.column("symmetric", sa.Boolean()),
    sa.column("transitive", sa.Boolean()),
    sa.column("metadata_json", postgresql.JSONB()),
)

# entity_type -> (description, parent_type)
_ONTOLOGY_SEED: dict[str, tuple[str, str | None]] = {
    "organization": (
        "A general organizational entity - governments, regulators, or "
        "businesses not otherwise typed as a company.",
        None,
    ),
    "port": ("A maritime or logistics port facility.", None),
    "country": ("A sovereign nation or jurisdiction.", None),
    "commodity": (
        "A tradable physical good, e.g. crude oil, thermal coal, iron ore.",
        None,
    ),
    "contract": ("A commercial agreement referencing one or more commodities.", None),
    "vessel": ("A ship used to transport commodities.", None),
    "company": (
        "A commercial business entity - the primary actor in ownership/operation relationships.",
        "organization",
    ),
    "terminal": ("A specific terminal within a port, operated by a company.", "port"),
}

# relationship_name -> (inverse_relationship, symmetric, transitive)
_RELATIONSHIP_SEED: dict[str, tuple[str | None, bool, bool]] = {
    "owns": ("owned_by", False, False),
    "owned_by": ("owns", False, False),
    "operates": ("operated_by", False, False),
    "operated_by": ("operates", False, False),
    "shipped_from": (None, False, False),
    "shipped_to": (None, False, False),
    "references": ("referenced_by", False, False),
    "referenced_by": ("references", False, False),
    # Geographic containment is transitive (A in B, B in C => A in C);
    # not symmetric (a country is not located in its own port).
    "located_in": ("contains", False, True),
    "contains": ("located_in", False, True),
}


def upgrade() -> None:
    op.create_table(
        "ontology_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parent_type", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_type"],
            ["ontology_types.entity_type"],
            name=op.f("fk_ontology_types_parent_type_ontology_types"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ontology_types")),
        sa.UniqueConstraint("entity_type", name=op.f("uq_ontology_types_entity_type")),
    )
    op.create_table(
        "relationship_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("relationship_name", sa.String(length=64), nullable=False),
        sa.Column("inverse_relationship", sa.String(length=64), nullable=True),
        sa.Column("symmetric", sa.Boolean(), nullable=False),
        sa.Column("transitive", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["inverse_relationship"],
            ["relationship_types.relationship_name"],
            name=op.f("fk_relationship_types_inverse_relationship_relationship_types"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationship_types")),
        sa.UniqueConstraint(
            "relationship_name", name=op.f("uq_relationship_types_relationship_name")
        ),
    )
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_id", sa.String(length=256), nullable=False),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("aliases_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "merged", name="graph_node_status"),
            nullable=False,
        ),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
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
            ["merged_into_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_nodes_merged_into_id_graph_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_type"],
            ["ontology_types.entity_type"],
            name=op.f("fk_graph_nodes_node_type_ontology_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_nodes")),
        sa.UniqueConstraint("canonical_id", name=op.f("uq_graph_nodes_canonical_id")),
    )
    op.create_table(
        "graph_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_node_id", sa.UUID(), nullable=False),
        sa.Column("target_node_id", sa.UUID(), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            ["relationship_type"],
            ["relationship_types.relationship_name"],
            name=op.f("fk_graph_edges_relationship_type_relationship_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_source_node_id_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_target_node_id_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_edges")),
        sa.UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "relationship_type",
            name="uq_graph_edges_source_target_relationship",
        ),
    )
    op.create_table(
        "graph_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("edge_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("extraction_run_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_graph_evidence_chunk_id_document_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_graph_evidence_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["edge_id"],
            ["graph_edges.id"],
            name=op.f("fk_graph_evidence_edge_id_graph_edges"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["extracted_entities.id"],
            name=op.f("fk_graph_evidence_entity_id_extracted_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["extraction_runs.id"],
            name=op.f("fk_graph_evidence_extraction_run_id_extraction_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_evidence")),
        sa.UniqueConstraint(
            "edge_id", "entity_id", "chunk_id", name="uq_graph_evidence_edge_entity_chunk"
        ),
    )
    op.create_table(
        "graph_build_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("extraction_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", name="graph_build_status"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("runs_processed", sa.Integer(), nullable=False),
        sa.Column("nodes_created", sa.Integer(), nullable=False),
        sa.Column("nodes_updated", sa.Integer(), nullable=False),
        sa.Column("edges_created", sa.Integer(), nullable=False),
        sa.Column("edges_updated", sa.Integer(), nullable=False),
        sa.Column("evidence_created", sa.Integer(), nullable=False),
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
            name=op.f("fk_graph_build_runs_extraction_run_id_extraction_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_build_runs")),
    )

    _seed_reference_data()


def _seed_reference_data() -> None:
    import uuid

    ontology_ids = {entity_type: uuid.uuid4() for entity_type in _ONTOLOGY_SEED}
    op.bulk_insert(
        _ontology_types,
        [
            {
                "id": ontology_ids[entity_type],
                "entity_type": entity_type,
                "description": description,
                "parent_type": None,
                "metadata_json": {},
            }
            for entity_type, (description, _parent) in _ONTOLOGY_SEED.items()
        ],
    )
    for entity_type, (_description, parent_type) in _ONTOLOGY_SEED.items():
        if parent_type is not None:
            op.execute(
                sa.text(
                    "UPDATE ontology_types SET parent_type = :parent_type "
                    "WHERE entity_type = :entity_type"
                ).bindparams(parent_type=parent_type, entity_type=entity_type)
            )

    relationship_ids = {name: uuid.uuid4() for name in _RELATIONSHIP_SEED}
    op.bulk_insert(
        _relationship_types,
        [
            {
                "id": relationship_ids[name],
                "relationship_name": name,
                "inverse_relationship": None,
                "symmetric": symmetric,
                "transitive": transitive,
                "metadata_json": {},
            }
            for name, (_inverse, symmetric, transitive) in _RELATIONSHIP_SEED.items()
        ],
    )
    for name, (inverse, _symmetric, _transitive) in _RELATIONSHIP_SEED.items():
        if inverse is not None:
            op.execute(
                sa.text(
                    "UPDATE relationship_types SET inverse_relationship = :inverse "
                    "WHERE relationship_name = :name"
                ).bindparams(inverse=inverse, name=name)
            )


def downgrade() -> None:
    op.drop_table("graph_build_runs")
    op.drop_table("graph_evidence")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("relationship_types")
    op.drop_table("ontology_types")

    # drop_table() does not drop the native Postgres ENUM types
    # create_table() implicitly created - see 11f8364050e2 (Phase 3.3)
    # for the same fix.
    bind = op.get_bind()
    sa.Enum(name="graph_build_status").drop(bind, checkfirst=True)
    sa.Enum(name="graph_node_status").drop(bind, checkfirst=True)
