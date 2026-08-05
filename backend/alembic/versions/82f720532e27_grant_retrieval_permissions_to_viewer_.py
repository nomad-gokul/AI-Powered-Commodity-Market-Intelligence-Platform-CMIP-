"""grant retrieval permissions to viewer and analyst roles

Retrieval is a read-only capability from the caller's perspective, even
though it performs real computation (BM25 + vector search + graph
expansion) and persists a RetrievalRun as a side effect - the same
precedent graph:read set for subgraph/neighbors traversal. No separate
"trigger" verb: unlike extraction/trust/graph, there is nothing to
irreversibly mutate business data here, so viewer and analyst get the
identical grant.

Revision ID: 82f720532e27
Revises: 68a87ef077e4
Create Date: 2026-08-04 02:16:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "82f720532e27"
down_revision: str | None = "68a87ef077e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWER_GRANTS = ["retrieval:read"]
ANALYST_GRANTS = ["retrieval:read"]


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || :grants WHERE name = 'viewer'"
        ).bindparams(sa.bindparam("grants", value=VIEWER_GRANTS, type_=sa.ARRAY(sa.String)))
    )
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || :grants WHERE name = 'analyst'"
        ).bindparams(sa.bindparam("grants", value=ANALYST_GRANTS, type_=sa.ARRAY(sa.String)))
    )


def downgrade() -> None:
    for permission in VIEWER_GRANTS:
        op.execute(
            sa.text(
                "UPDATE roles SET permissions = array_remove(permissions, :permission) "
                "WHERE name = 'viewer'"
            ).bindparams(sa.bindparam("permission", value=permission))
        )
    for permission in ANALYST_GRANTS:
        op.execute(
            sa.text(
                "UPDATE roles SET permissions = array_remove(permissions, :permission) "
                "WHERE name = 'analyst'"
            ).bindparams(sa.bindparam("permission", value=permission))
        )
