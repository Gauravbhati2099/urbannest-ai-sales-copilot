"""expand user role column for co-owner values

Revision ID: e81d49a60bc2
Revises: 91f2c46a8d10
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e81d49a60bc2"
down_revision: Union[str, Sequence[str], None] = "91f2c46a8d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=7),
        type_=sa.String(length=8),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=8),
        type_=sa.String(length=7),
        existing_nullable=False,
    )
