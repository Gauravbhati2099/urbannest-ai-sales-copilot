"""add private chat history with 30-day retention

Revision ID: ca8b7d2e10f4
Revises: b84c71d29a60
Create Date: 2026-11-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ca8b7d2e10f4"
down_revision: Union[str, Sequence[str], None] = "b84c71d29a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "next_message_sequence",
            sa.Integer(),
            server_default=sa.text("0"),
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
            ["user_id", "team_id"],
            ["users.id", "users.team_id"],
            name="fk_chat_conversations_user_team",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "next_message_sequence >= 0",
            name="ck_chat_conversations_next_message_sequence",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "team_id",
            "user_id",
            name="uq_chat_conversations_id_team_user",
        ),
    )
    op.create_index(
        "ix_chat_conversations_user_activity",
        "chat_conversations",
        ["user_id", "team_id", "updated_at"],
    )
    op.create_index(
        "ix_chat_conversations_updated_at",
        "chat_conversations",
        ["updated_at"],
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "tool_executions",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_chat_messages_role",
        ),
        sa.CheckConstraint(
            "length(content) BETWEEN 1 AND 8000",
            name="ck_chat_messages_content_length",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_chat_messages_sequence"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "team_id", "user_id"],
            [
                "chat_conversations.id",
                "chat_conversations.team_id",
                "chat_conversations.user_id",
            ],
            name="fk_chat_messages_conversation_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "team_id",
            "user_id",
            "sequence",
            name="uq_chat_messages_conversation_sequence",
        ),
    )
    op.create_index(
        "ix_chat_messages_conversation_sequence",
        "chat_messages",
        ["conversation_id", "team_id", "user_id", "sequence"],
    )
    op.create_index(
        "ix_chat_messages_created_at",
        "chat_messages",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_messages_created_at",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_messages_conversation_sequence",
        table_name="chat_messages",
    )
    op.drop_table("chat_messages")
    op.drop_index(
        "ix_chat_conversations_updated_at",
        table_name="chat_conversations",
    )
    op.drop_index(
        "ix_chat_conversations_user_activity",
        table_name="chat_conversations",
    )
    op.drop_table("chat_conversations")
