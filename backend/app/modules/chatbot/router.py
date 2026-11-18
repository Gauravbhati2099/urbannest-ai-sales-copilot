from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Literal, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.dependencies import CurrentUser, DatabaseSession, bearer_scheme
from app.db.models import ChatConversation, ChatMessage, User
from app.modules.ai.service import AIServiceError, redact_contact_details
from app.modules.chatbot.orchestrator import answer_chat_message
from app.modules.chatbot.schemas import (
    ChatConversationSummary,
    ChatMessageRead,
    ChatRequest,
    ChatResponse,
    ChatToolExecution,
)
from app.modules.chatbot.storage import (
    delete_owned_conversation,
    get_owned_conversation,
    get_recent_chat_history,
    list_chat_messages,
    list_owned_conversations,
    purge_expired_chat_data,
)

LOGGER = logging.getLogger("urbannest.chatbot")
router = APIRouter(prefix="/chat", tags=["chat"])
AccessCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


def _storage_unavailable(session: DatabaseSession, error: SQLAlchemyError) -> NoReturn:
    session.rollback()
    LOGGER.warning("Chat history operation failed: %s", type(error).__name__)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Chat history is temporarily unavailable",
    ) from None


def _conversation_title(message: str) -> str:
    title = " ".join(message.split())
    return redact_contact_details(title, maximum_length=120) or "New conversation"


def _chat_execution_rows(
    executions: list[ChatToolExecution],
) -> list[dict[str, str]]:
    return [execution.model_dump() for execution in executions]


def _message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=message.id,
        role=cast(Literal["user", "assistant"], message.role),
        content=message.content,
        created_at=message.created_at,
        tool_executions=[
            ChatToolExecution.model_validate(execution)
            for execution in message.tool_executions
        ],
    )


@router.get("/conversations", response_model=list[ChatConversationSummary])
def list_chat_conversations(
    current_user: CurrentUser,
    session: DatabaseSession,
) -> list[ChatConversationSummary]:
    try:
        purge_expired_chat_data(session)
        conversations = list_owned_conversations(session, user=current_user)
        return [
            ChatConversationSummary(
                id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
            for conversation in conversations
        ]
    except SQLAlchemyError as exc:
        _storage_unavailable(session, exc)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageRead],
)
def read_chat_messages(
    conversation_id: UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> list[ChatMessageRead]:
    try:
        purge_expired_chat_data(session)
        conversation = get_owned_conversation(
            session,
            conversation_id=conversation_id,
            user=current_user,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = list_chat_messages(session, conversation=conversation)
        return [_message_read(message) for message in messages]
    except SQLAlchemyError as exc:
        _storage_unavailable(session, exc)


@router.post("/messages", response_model=ChatResponse)
async def send_chat_message(
    payload: ChatRequest,
    current_user: CurrentUser,
    credentials: AccessCredentials,
    session: DatabaseSession,
) -> ChatResponse:
    LOGGER.info("[chat-trace] request received user_id=%s", current_user.id)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    history: list[dict[str, str]] = []
    try:
        LOGGER.info("[chat-trace] loading conversation history")
        purge_expired_chat_data(session)
        if payload.conversation_id is not None:
            conversation = get_owned_conversation(
                session,
                conversation_id=payload.conversation_id,
                user=current_user,
            )
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            history = get_recent_chat_history(session, conversation=conversation)
        session.rollback()
        LOGGER.info("[chat-trace] conversation history ready messages=%s", len(history))
    except SQLAlchemyError as exc:
        _storage_unavailable(session, exc)

    try:
        LOGGER.info("[chat-trace] entering chat orchestrator")
        result = await answer_chat_message(
            payload.message,
            credentials.credentials,
            history,
        )
        LOGGER.info("[chat-trace] orchestrator completed tool_calls=%s", len(result.tool_executions))
    except AIServiceError as exc:
        LOGGER.warning("Chat request failed: %s", exc.category)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service is unavailable",
        ) from None

    try:
        LOGGER.info("[chat-trace] saving assistant response")
        now = datetime.now(timezone.utc)
        if payload.conversation_id is None:
            conversation = ChatConversation(
                team_id=current_user.team_id,
                user_id=current_user.id,
                title=_conversation_title(payload.message),
            )
            session.add(conversation)
            session.flush()
        else:
            conversation = get_owned_conversation(
                session,
                conversation_id=payload.conversation_id,
                user=current_user,
                now=now,
                for_update=True,
            )
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            conversation.title = _conversation_title(payload.message)

        first_sequence = conversation.next_message_sequence
        conversation.next_message_sequence = first_sequence + 2
        conversation.updated_at = now
        session.add_all(
            [
                ChatMessage(
                    conversation_id=conversation.id,
                    team_id=current_user.team_id,
                    user_id=current_user.id,
                    sequence=first_sequence,
                    role="user",
                    content=payload.message,
                    tool_executions=[],
                ),
                ChatMessage(
                    conversation_id=conversation.id,
                    team_id=current_user.team_id,
                    user_id=current_user.id,
                    sequence=first_sequence + 1,
                    role="assistant",
                    content=result.response,
                    tool_executions=_chat_execution_rows(result.tool_executions),
                ),
            ]
        )
        session.commit()
        LOGGER.info("[chat-trace] response saved")
        conversation_id = conversation.id
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        _storage_unavailable(session, exc)

    return ChatResponse(
        response=result.response,
        tool_executions=result.tool_executions,
        conversation_id=conversation_id,
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_chat_conversation(
    conversation_id: UUID,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> Response:
    try:
        purge_expired_chat_data(session)
        conversation = get_owned_conversation(
            session,
            conversation_id=conversation_id,
            user=current_user,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        delete_owned_conversation(session, conversation=conversation)
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        _storage_unavailable(session, exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
