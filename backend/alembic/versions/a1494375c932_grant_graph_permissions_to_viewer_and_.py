"""grant graph permissions to viewer and analyst roles

The graph is a genuinely new resource with a genuinely new actor
capability (rebuilding/correcting a corpus-wide structure), unlike
trust's decision to reuse extraction's permissions - see
app/modules/graph/api.py. Same grant shape as ec2182df58d8 (Phase 3.3):
viewer gets read, analyst additionally gets the trigger/correction verb,
admin already has "*" and needs no change.

Revision ID: a1494375c932
Revises: 59226041fb77
Create Date: 2026-08-04 01:43:57.844737
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1494375c932"
down_revision: str | None = "59226041fb77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWER_GRANTS = ["graph:read"]
ANALYST_GRANTS = ["graph:rebuild", "graph:read"]


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
