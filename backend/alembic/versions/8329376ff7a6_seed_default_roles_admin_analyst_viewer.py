"""seed default roles: admin, analyst, viewer

Permission lists only cover what Phase 1 actually has (auth/audit). Later
phases append their own permission strings to these roles via a new
migration (or an admin editing role.permissions) - the permissions column
is just a data value, so this never needs a schema change.

Revision ID: 8329376ff7a6
Revises: 568c56e752ae
Create Date: 2026-08-02 19:52:30.000286
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import column, table

from alembic import op

revision: str = '8329376ff7a6'
down_revision: str | None = '568c56e752ae'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

roles_table = table(
    "roles",
    column("id", postgresql.UUID(as_uuid=True)),
    column("name", sa.String),
    column("description", sa.String),
    column("permissions", postgresql.ARRAY(sa.String)),
)

DEFAULT_ROLES = [
    {
        "id": uuid.uuid4(),
        "name": "admin",
        "description": "Full platform access, including user and role management.",
        "permissions": ["*"],
    },
    {
        "id": uuid.uuid4(),
        "name": "analyst",
        "description": "Day-to-day platform user. Can view the audit trail.",
        "permissions": ["audit_logs:read"],
    },
    {
        "id": uuid.uuid4(),
        "name": "viewer",
        "description": "Default role for self-registered accounts. Read-only baseline.",
        "permissions": [],
    },
]


def upgrade() -> None:
    op.bulk_insert(roles_table, DEFAULT_ROLES)


def downgrade() -> None:
    op.execute(roles_table.delete().where(roles_table.c.name.in_(["admin", "analyst", "viewer"])))
