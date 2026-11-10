"""add optional user phone number

Revision ID: 4c8f21d7a602
Revises: a27dc638105b
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4c8f21d7a602"
down_revision: Union[str, Sequence[str], None] = "a27dc638105b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "phone")
