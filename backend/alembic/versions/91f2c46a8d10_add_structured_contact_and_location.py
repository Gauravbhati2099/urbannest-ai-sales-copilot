"""add structured contact and location data

Revision ID: 91f2c46a8d10
Revises: a27dc638105b, aa67c6a3f5db
Create Date: 2026-11-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "91f2c46a8d10"
down_revision: Union[str, Sequence[str], None] = (
    "a27dc638105b",
    "aa67c6a3f5db",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("manager_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_users_manager_team",
        "users",
        "users",
        ["manager_id", "team_id"],
        ["id", "team_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_users_manager_id", "users", ["manager_id"])
    for table in ("users", "leads"):
        op.add_column(
            table, sa.Column("phone_country_code", sa.String(length=5), nullable=True)
        )
        op.add_column(
            table, sa.Column("phone_region", sa.String(length=2), nullable=True)
        )
        op.add_column(
            table,
            sa.Column("phone_national_number", sa.String(length=20), nullable=True),
        )
    op.add_column("leads", sa.Column("location", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "location")
    for table in ("leads", "users"):
        op.drop_column(table, "phone_national_number")
        op.drop_column(table, "phone_region")
        op.drop_column(table, "phone_country_code")
    op.drop_index("ix_users_manager_id", table_name="users")
    op.drop_constraint("fk_users_manager_team", "users", type_="foreignkey")
    op.drop_column("users", "manager_id")
