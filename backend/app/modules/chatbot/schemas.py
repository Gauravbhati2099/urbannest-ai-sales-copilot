from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class ChatToolExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["succeeded", "failed"]


class ChatTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str = Field(min_length=1, max_length=8000)
    tool_executions: list[ChatToolExecution]


class ChatResponse(ChatTurnResult):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID


class ChatConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    tool_executions: list[ChatToolExecution]
