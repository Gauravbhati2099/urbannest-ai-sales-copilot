"""add shared audit events and notification cursors

Revision ID: f6b6d24a8910
Revises: c13a7f6d2e90
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f6b6d24a8910"
down_revision: Union[str, Sequence[str], None] = "c13a7f6d2e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column(
            "visibility",
            sa.Enum(
                "team",
                "actor",
                "admin",
                name="audit_visibility",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column(
            "changes",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()),
                "postgresql",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_audit_events_actor_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id", "team_id"],
            ["leads.id", "leads.team_id"],
            name="fk_audit_events_lead_team",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_team_created",
        "audit_events",
        ["team_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_team_lead_created",
        "audit_events",
        ["team_id", "lead_id", "created_at"],
    )
    op.create_table(
        "audit_read_cursors",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_audit_read_cursors_user_team",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute(
        """
        CREATE FUNCTION notify_audit_event() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'audit_events',
                json_build_object(
                    'event_id', NEW.id::text,
                    'team_id', NEW.team_id::text
                )::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_notify_insert
        AFTER INSERT ON audit_events
        FOR EACH ROW EXECUTE FUNCTION notify_audit_event()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_notify_insert ON audit_events")
    op.execute("DROP FUNCTION notify_audit_event()")
    op.drop_table("audit_read_cursors")
    op.drop_index("ix_audit_events_team_lead_created", table_name="audit_events")
    op.drop_index("ix_audit_events_team_created", table_name="audit_events")
    op.drop_table("audit_events")
