"""grant extraction permissions to viewer and analyst roles

Extends the Phase 1 seeded roles, same pattern as 5cf29ad980c9 (Phase 2's
documents grants): viewer gets extraction:read (can see results once
someone else triggers a run); analyst additionally gets extraction:trigger
(can start a new run); admin already has "*" and needs no change.

Revision ID: ec2182df58d8
Revises: 23293813c565
Create Date: 2026-08-03 13:17:36.950422
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ec2182df58d8"
down_revision: str | None = "23293813c565"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWER_GRANTS = ["extraction:read"]
ANALYST_GRANTS = ["extraction:trigger", "extraction:read"]


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
