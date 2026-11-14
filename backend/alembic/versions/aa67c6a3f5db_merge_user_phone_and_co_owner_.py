"""merge user phone and co-owner permissions migrations

Revision ID: aa67c6a3f5db
Revises: 4c8f21d7a602, 82a4c19e6b31
Create Date: 2026-11-12 16:12:24.505801

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa67c6a3f5db'
down_revision: Union[str, Sequence[str], None] = ('4c8f21d7a602', '82a4c19e6b31')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
