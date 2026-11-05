from enum import StrEnum
from uuid import UUID

from pydantic import Field

from .common import ContractModel, new_id
from .intake import ConsultationProgress


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(ContractModel):
    id: UUID = Field(default_factory=new_id)
    role: MessageRole
    content: str = Field(min_length=1, max_length=8_000)
    source_references: list[UUID] = Field(default_factory=list, max_length=50)


class ChatRequest(ContractModel):
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=8_000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=100)


class RedactRequest(ContractModel):
    text: str = Field(min_length=1, max_length=8_000)


class ChatAction(ContractModel):
    action_id: str = Field(min_length=1, max_length=80)
    type: str = Field(default="message", min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=200)
    payload: str = Field(min_length=1, max_length=8_000)
    relevance: str = Field(min_length=1, max_length=200)


class ChatResponse(ContractModel):
    conversation_id: UUID
    message: ChatMessage
    source_references: list[UUID] = Field(default_factory=list, max_length=50)
    conversation_state: str = "requested"
    next_action: str = "answer"
    suggestions: list[ChatAction] = Field(default_factory=list, max_length=5)
    suggested_actions: list[ChatAction] = Field(default_factory=list, max_length=5)
    consultation_progress: ConsultationProgress | None = None
    profile_summary: dict[str, object] = Field(default_factory=dict)
    escalated: bool = False
