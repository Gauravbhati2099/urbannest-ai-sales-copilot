"""add co-owner permissions and development superuser flag

Revision ID: 82a4c19e6b31
Revises: f6b6d24a8910
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "82a4c19e6b31"
down_revision: Union[str, Sequence[str], None] = "f6b6d24a8910"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "can_read",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "can_write",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "can_delete",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "can_manage_users",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("user_role", type_="check")
        batch_op.create_check_constraint(
            "user_role", "role IN ('owner', 'co_owner', 'manager', 'agent')"
        )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'manager' WHERE role = 'co_owner'")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("user_role", type_="check")
        batch_op.create_check_constraint(
            "user_role", "role IN ('owner', 'manager', 'agent')"
        )
    op.drop_column("users", "can_manage_users")
    op.drop_column("users", "can_delete")
    op.drop_column("users", "can_write")
    op.drop_column("users", "can_read")
    op.drop_column("users", "is_superuser")
