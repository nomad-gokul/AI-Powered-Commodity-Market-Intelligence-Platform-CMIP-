"""grant documents permissions to viewer and analyst roles

Extends the Phase 1 seeded roles rather than replacing them - the
permissions column is a data value, not a schema, so appending to it here
matches the plan documented in the Phase 1 seed migration. viewer gets
upload+read (self-service use of the feature); analyst additionally gets
reprocess+delete; admin already has "*" and needs no change.

Revision ID: 5cf29ad980c9
Revises: 4d65d7e68757
Create Date: 2026-08-03 05:51:10.670248
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5cf29ad980c9"
down_revision: str | None = "4d65d7e68757"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWER_GRANTS = ["documents:upload", "documents:read"]
ANALYST_GRANTS = ["documents:upload", "documents:read", "documents:reprocess", "documents:delete"]


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
