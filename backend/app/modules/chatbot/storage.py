from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import ChatConversation, ChatMessage, User

CHAT_RETENTION_DAYS = 30
MAX_CONVERSATIONS = 50
MAX_MESSAGES_PER_CONVERSATION = 100
MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_CHARS = 10000
MAX_HISTORY_MESSAGE_CHARS = 2000


def retention_cutoff(now: datetime | None = None) -> datetime:
    current_time = now or datetime.now(timezone.utc)
    return current_time - timedelta(days=CHAT_RETENTION_DAYS)


def purge_expired_chat_data(
    session: Session,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    cutoff = retention_cutoff(now)
    expired_conversations = select(ChatConversation.id).where(
        ChatConversation.updated_at < cutoff
    )
    expired_message_count = session.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(
            or_(
                ChatMessage.created_at < cutoff,
                ChatMessage.conversation_id.in_(expired_conversations),
            )
        )
    ) or 0
    expired_conversation_count = session.scalar(
        select(func.count())
        .select_from(ChatConversation)
        .where(ChatConversation.updated_at < cutoff)
    ) or 0

    if expired_message_count:
        session.execute(
            delete(ChatMessage).where(
                or_(
                    ChatMessage.created_at < cutoff,
                    ChatMessage.conversation_id.in_(expired_conversations),
                )
            )
        )
    if expired_conversation_count:
        session.execute(
            delete(ChatConversation).where(ChatConversation.updated_at < cutoff)
        )
    if expired_message_count or expired_conversation_count:
        session.commit()
    return expired_conversation_count, expired_message_count


def get_owned_conversation(
    session: Session,
    *,
    conversation_id: UUID,
    user: User,
    now: datetime | None = None,
    for_update: bool = False,
) -> ChatConversation | None:
    statement = select(ChatConversation).where(
        ChatConversation.id == conversation_id,
        ChatConversation.team_id == user.team_id,
        ChatConversation.user_id == user.id,
        ChatConversation.updated_at >= retention_cutoff(now),
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def list_owned_conversations(
    session: Session,
    *,
    user: User,
    now: datetime | None = None,
) -> list[ChatConversation]:
    return list(
        session.scalars(
            select(ChatConversation)
            .where(
                ChatConversation.team_id == user.team_id,
                ChatConversation.user_id == user.id,
                ChatConversation.updated_at >= retention_cutoff(now),
            )
            .order_by(ChatConversation.updated_at.desc())
            .limit(MAX_CONVERSATIONS)
        ).all()
    )


def get_recent_chat_history(
    session: Session,
    *,
    conversation: ChatConversation,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    messages = session.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.team_id == conversation.team_id,
            ChatMessage.user_id == conversation.user_id,
            ChatMessage.created_at >= retention_cutoff(now),
        )
        .order_by(ChatMessage.sequence.desc())
        .limit(MAX_HISTORY_MESSAGES)
    ).all()

    recent_history: list[dict[str, str]] = []
    characters_used = 0
    for message in reversed(messages):
        remaining = MAX_HISTORY_CHARS - characters_used
        if remaining <= 0:
            break
        content = message.content[: min(MAX_HISTORY_MESSAGE_CHARS, remaining)]
        if content:
            recent_history.append({"role": message.role, "content": content})
            characters_used += len(content)
    return recent_history


def list_chat_messages(
    session: Session,
    *,
    conversation: ChatConversation,
    now: datetime | None = None,
) -> list[ChatMessage]:
    messages = session.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.team_id == conversation.team_id,
            ChatMessage.user_id == conversation.user_id,
            ChatMessage.created_at >= retention_cutoff(now),
        )
        .order_by(ChatMessage.sequence.desc())
        .limit(MAX_MESSAGES_PER_CONVERSATION)
    ).all()
    return list(reversed(messages))


def delete_owned_conversation(
    session: Session,
    *,
    conversation: ChatConversation,
) -> None:
    session.execute(
        delete(ChatMessage).where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.team_id == conversation.team_id,
            ChatMessage.user_id == conversation.user_id,
        )
    )
    session.delete(conversation)
    session.commit()
