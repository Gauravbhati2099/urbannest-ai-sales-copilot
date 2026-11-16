"""add estate inventory and sales tracking

Revision ID: b84c71d29a60
Revises: e81d49a60bc2
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b84c71d29a60"
down_revision: Union[str, Sequence[str], None] = "e81d49a60bc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type():
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )


def upgrade() -> None:
    op.create_table(
        "estates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column(
            "estate_type",
            sa.Enum(
                "flat",
                "plot",
                "house",
                "commercial_land",
                "farmland",
                "farmhouse",
                name="estate_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "available",
                "under_offer",
                "sold",
                "withdrawn",
                name="estate_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'available'"),
            nullable=False,
        ),
        sa.Column("location", _json_type(), nullable=False),
        sa.Column("asking_price_inr", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("details", _json_type(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "asking_price_inr IS NULL OR asking_price_inr >= 0",
            name="ck_estates_asking_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_estates_assignee_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "team_id", name="uq_estates_id_team"),
    )
    op.create_index("ix_estates_team_status", "estates", ["team_id", "status"])
    op.create_index("ix_estates_team_type", "estates", ["team_id", "estate_type"])
    op.create_index("ix_estates_team_assignee", "estates", ["team_id", "assigned_to"])

    op.create_table(
        "estate_interests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("estate_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "interested",
                "site_visit",
                "negotiation",
                "won",
                "lost",
                name="estate_interest_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'interested'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_estate_interests_creator_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["estate_id", "team_id"],
            ["estates.id", "estates.team_id"],
            name="fk_estate_interests_estate_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_estate_interests_lead_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "estate_id",
            "lead_id",
            "team_id",
            name="uq_estate_interests_estate_lead_team",
        ),
    )
    op.create_index(
        "ix_estate_interests_team_estate_status",
        "estate_interests",
        ["team_id", "estate_id", "status"],
    )
    op.create_index(
        "ix_estate_interests_team_lead",
        "estate_interests",
        ["team_id", "lead_id"],
    )

    op.create_table(
        "estate_visits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("estate_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("visited_by", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["estate_id", "team_id"],
            ["estates.id", "estates.team_id"],
            name="fk_estate_visits_estate_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_estate_visits_lead_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["visited_by", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_estate_visits_user_team",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_estate_visits_team_estate_occurred",
        "estate_visits",
        ["team_id", "estate_id", "occurred_at"],
    )
    op.create_index(
        "ix_estate_visits_team_lead_occurred",
        "estate_visits",
        ["team_id", "lead_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_estate_visits_team_lead_occurred", table_name="estate_visits")
    op.drop_index("ix_estate_visits_team_estate_occurred", table_name="estate_visits")
    op.drop_table("estate_visits")
    op.drop_index("ix_estate_interests_team_lead", table_name="estate_interests")
    op.drop_index(
        "ix_estate_interests_team_estate_status", table_name="estate_interests"
    )
    op.drop_table("estate_interests")
    op.drop_index("ix_estates_team_assignee", table_name="estates")
    op.drop_index("ix_estates_team_type", table_name="estates")
    op.drop_index("ix_estates_team_status", table_name="estates")
    op.drop_table("estates")
